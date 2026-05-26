from django.db import transaction
from django.db.models import Count, DecimalField, Q, QuerySet, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.models import AuditLog
from apps.normalization.models import NormalizedActivity

from .serializers import ActivityEditSerializer, BulkApproveSerializer, NormalizedActivityListSerializer, ReviewActionSerializer


class LockedActivityError(Exception):
    pass


def _get_client_ip(request) -> str:
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def _snapshot(activity: NormalizedActivity) -> dict:
    # Ensure the snapshot contains only JSON-serializable values (UUIDs -> strings)
    import json

    raw = NormalizedActivityListSerializer(activity).data
    return json.loads(json.dumps(raw, default=str))


def _write_audit(*, activity: NormalizedActivity, actor, action: str, before: dict, after: dict, detail: str, ip: str):
    AuditLog.objects.create(
        tenant=activity.tenant,
        actor=actor,
        action=action,
        target_type="normalized_activity",
        target_id=activity.id,
        before_state=before,
        after_state=after,
        detail=detail,
        ip_address=ip,
    )


def _transition_activity(*, activity: NormalizedActivity, actor, action: str, new_status: str, note: str | None, ip: str):
    if activity.review_status == NormalizedActivity.ReviewStatus.LOCKED:
        raise LockedActivityError()

    before = _snapshot(activity)
    activity.review_status = new_status
    activity.reviewed_by = actor
    activity.reviewed_at = timezone.now()
    if note is not None:
        activity.review_note = note
    if new_status == NormalizedActivity.ReviewStatus.FLAGGED:
        activity.is_flagged_suspicious = True
    activity.save()
    after = _snapshot(activity)

    _write_audit(
        activity=activity,
        actor=actor,
        action=action,
        before=before,
        after=after,
        detail=note or f"{action.replace('_', ' ')} via review endpoint",
        ip=ip,
    )
    return activity


class NormalizedActivityViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = NormalizedActivityListSerializer

    def get_queryset(self) -> QuerySet[NormalizedActivity]:
        qs = (
            NormalizedActivity.objects.filter(tenant=self.request.user.tenant)
            .select_related("ingestion_run", "reviewed_by", "edited_by")
            .order_by("-activity_date", "-created_at")
        )

        scope = self.request.query_params.get("scope")
        if scope:
            qs = qs.filter(scope=scope)

        review_status = self.request.query_params.get("review_status")
        if review_status:
            qs = qs.filter(review_status=review_status)

        source_type = self.request.query_params.get("source_type")
        if source_type:
            qs = qs.filter(ingestion_run__source_type=source_type)

        flagged = self.request.query_params.get("flagged")
        if flagged is not None:
            normalized = flagged.strip().lower()
            if normalized in {"true", "1", "yes"}:
                qs = qs.filter(is_flagged_suspicious=True)
            elif normalized in {"false", "0", "no"}:
                qs = qs.filter(is_flagged_suspicious=False)

        run_id = self.request.query_params.get("run_id")
        if run_id:
            qs = qs.filter(ingestion_run_id=run_id)

        return qs

    @action(detail=True, methods=["post"], url_path="approve")
    def approve(self, request, pk=None):
        serializer = ReviewActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            with transaction.atomic():
                activity = self.get_object()
                updated = _transition_activity(
                    activity=activity,
                    actor=request.user,
                    action=AuditLog.Action.ACTIVITY_APPROVED,
                    new_status=NormalizedActivity.ReviewStatus.APPROVED,
                    note=serializer.validated_data.get("note"),
                    ip=_get_client_ip(request),
                )
        except LockedActivityError:
            return Response(
                {"detail": "This activity is locked and cannot be modified."},
                status=status.HTTP_409_CONFLICT,
            )

        return Response(self.get_serializer(updated).data)

    @action(detail=True, methods=["post"], url_path="flag")
    def flag(self, request, pk=None):
        serializer = ReviewActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        note = serializer.validated_data.get("note")
        if not note:
            return Response(
                {"note": ["This field is required."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            with transaction.atomic():
                activity = self.get_object()
                updated = _transition_activity(
                    activity=activity,
                    actor=request.user,
                    action=AuditLog.Action.ACTIVITY_FLAGGED,
                    new_status=NormalizedActivity.ReviewStatus.FLAGGED,
                    note=note,
                    ip=_get_client_ip(request),
                )
        except LockedActivityError:
            return Response(
                {"detail": "This activity is locked and cannot be modified."},
                status=status.HTTP_409_CONFLICT,
            )

        return Response(self.get_serializer(updated).data)

    @action(detail=True, methods=["post"], url_path="lock")
    def lock(self, request, pk=None):
        serializer = ReviewActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            with transaction.atomic():
                activity = self.get_object()
                updated = _transition_activity(
                    activity=activity,
                    actor=request.user,
                    action=AuditLog.Action.ACTIVITY_LOCKED,
                    new_status=NormalizedActivity.ReviewStatus.LOCKED,
                    note=serializer.validated_data.get("note"),
                    ip=_get_client_ip(request),
                )
        except LockedActivityError:
            return Response(
                {"detail": "This activity is locked and cannot be modified."},
                status=status.HTTP_409_CONFLICT,
            )

        return Response(self.get_serializer(updated).data)

    @action(detail=False, methods=["post"], url_path="bulk-approve")
    def bulk_approve(self, request):
        serializer = BulkApproveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ids = list(dict.fromkeys(serializer.validated_data["ids"]))
        ip = _get_client_ip(request)

        with transaction.atomic():
            activities = list(self.get_queryset().filter(id__in=ids))
            activity_map = {activity.id: activity for activity in activities}

            if len(activity_map) != len(ids):
                return Response(
                    {"detail": "One or more activities were not found."},
                    status=status.HTTP_404_NOT_FOUND,
                )

            for activity in activities:
                if activity.review_status == NormalizedActivity.ReviewStatus.LOCKED:
                    return Response(
                        {"detail": "One or more activities are locked and cannot be modified."},
                        status=status.HTTP_409_CONFLICT,
                    )

            updated = []
            for activity in activities:
                updated.append(
                    _transition_activity(
                        activity=activity,
                        actor=request.user,
                        action=AuditLog.Action.BULK_APPROVED,
                        new_status=NormalizedActivity.ReviewStatus.APPROVED,
                        note=None,
                        ip=ip,
                    )
                )

        return Response(
            {
                "updated": len(updated),
                "results": self.get_serializer(updated, many=True).data,
            }
        )

    @action(detail=True, methods=["post"], url_path="edit")
    def edit(self, request, pk=None):
        """
        POST /api/review/activities/:id/edit/

        Edit a flagged/warning activity to fix data issues.
        Accepts any subset of editable fields. CO2 is automatically
        recalculated when original_value changes.

        When clear_flags=true (default), the activity's suspicious flags
        are cleared and the raw_row status is set back to OK.
        """
        serializer = ActivityEditSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            with transaction.atomic():
                activity = self.get_object()

                if activity.review_status == NormalizedActivity.ReviewStatus.LOCKED:
                    return Response(
                        {"detail": "This activity is locked and cannot be modified."},
                        status=status.HTTP_409_CONFLICT,
                    )

                before = _snapshot(activity)
                ip = _get_client_ip(request)

                # Track which fields were changed
                changed_fields = []

                # --- Update simple text/date fields ---
                simple_fields = [
                    "original_unit", "original_amount", "original_currency",
                    "activity_date", "period_end", "description",
                    "facility_code", "facility_name", "cost_center",
                    "vendor", "country_code",
                ]
                for field in simple_fields:
                    if field in data:
                        old_val = getattr(activity, field)
                        new_val = data[field]
                        if str(old_val) != str(new_val):
                            setattr(activity, field, new_val)
                            changed_fields.append(field)

                # --- Update original_value and recalculate CO2 ---
                if "original_value" in data:
                    old_value = activity.original_value
                    new_value = data["original_value"]
                    if old_value != new_value:
                        activity.original_value = new_value
                        changed_fields.append("original_value")

                        # Recalculate CO2: new_value × existing emission factor
                        from decimal import Decimal
                        ef = activity.emission_factor_used
                        activity.normalized_kg_co2e = round(new_value * ef, 6)
                        changed_fields.append("normalized_kg_co2e")

                # --- Clear flags if requested ---
                clear_flags = data.get("clear_flags", True)
                if clear_flags:
                    if activity.is_flagged_suspicious:
                        activity.is_flagged_suspicious = False
                        activity.flag_reasons = []
                        changed_fields.extend(["is_flagged_suspicious", "flag_reasons"])

                    # Also update the raw_row status
                    raw_row = activity.raw_row
                    if raw_row.parse_status != "ok":
                        raw_row.parse_status = "ok"
                        raw_row.parse_errors = []
                        raw_row.save(update_fields=["parse_status", "parse_errors"])

                    # Set review status to pending for re-review
                    if activity.review_status in (
                        NormalizedActivity.ReviewStatus.FLAGGED,
                        NormalizedActivity.ReviewStatus.PENDING,
                    ):
                        activity.review_status = NormalizedActivity.ReviewStatus.PENDING
                        changed_fields.append("review_status")

                # --- Mark as edited ---
                activity.was_edited = True
                activity.edited_by = request.user
                activity.edited_at = timezone.now()
                activity.edit_note = data.get("edit_note", "")

                # Also update raw_data on the raw_row to reflect edits
                raw_row = activity.raw_row
                raw_data = dict(raw_row.raw_data) if raw_row.raw_data else {}
                field_to_raw_key = {
                    "original_value": _guess_raw_key(raw_data, activity.activity_type, "value"),
                    "cost_center": _guess_raw_key(raw_data, activity.activity_type, "cost_center"),
                    "facility_code": _guess_raw_key(raw_data, activity.activity_type, "facility_code"),
                    "vendor": _guess_raw_key(raw_data, activity.activity_type, "vendor"),
                }
                for field_name, raw_key in field_to_raw_key.items():
                    if field_name in data and raw_key:
                        raw_data[raw_key] = str(data[field_name])
                raw_row.raw_data = raw_data
                raw_row.save(update_fields=["raw_data"])

                activity.save()
                after = _snapshot(activity)

                # Write audit log
                edit_note = data.get("edit_note", "")
                detail = (
                    f"Activity edited by {request.user}. "
                    f"Fields changed: {', '.join(changed_fields) or 'none'}. "
                    f"Note: {edit_note or 'No note provided.'}"
                )
                _write_audit(
                    activity=activity,
                    actor=request.user,
                    action=AuditLog.Action.ACTIVITY_EDITED,
                    before=before,
                    after=after,
                    detail=detail,
                    ip=ip,
                )

        except LockedActivityError:
            return Response(
                {"detail": "This activity is locked and cannot be modified."},
                status=status.HTTP_409_CONFLICT,
            )

        return Response(self.get_serializer(activity).data)


class ReviewSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = NormalizedActivity.objects.filter(tenant=request.user.tenant)
        summary = qs.aggregate(
            scope_1_kg_co2e=Coalesce(
                Sum(
                    "normalized_kg_co2e",
                    filter=Q(scope=NormalizedActivity.Scope.SCOPE_1),
                ),
                Value(0, output_field=DecimalField(max_digits=24, decimal_places=6)),
                output_field=DecimalField(max_digits=24, decimal_places=6),
            ),
            scope_2_kg_co2e=Coalesce(
                Sum(
                    "normalized_kg_co2e",
                    filter=Q(scope=NormalizedActivity.Scope.SCOPE_2),
                ),
                Value(0, output_field=DecimalField(max_digits=24, decimal_places=6)),
                output_field=DecimalField(max_digits=24, decimal_places=6),
            ),
            scope_3_kg_co2e=Coalesce(
                Sum(
                    "normalized_kg_co2e",
                    filter=Q(scope=NormalizedActivity.Scope.SCOPE_3),
                ),
                Value(0, output_field=DecimalField(max_digits=24, decimal_places=6)),
                output_field=DecimalField(max_digits=24, decimal_places=6),
            ),
            pending_count=Count("id", filter=Q(review_status=NormalizedActivity.ReviewStatus.PENDING)),
            approved_count=Count("id", filter=Q(review_status=NormalizedActivity.ReviewStatus.APPROVED)),
            flagged_count=Count("id", filter=Q(review_status=NormalizedActivity.ReviewStatus.FLAGGED)),
            locked_count=Count("id", filter=Q(review_status=NormalizedActivity.ReviewStatus.LOCKED)),
            sap_mb51_count=Count("id", filter=Q(ingestion_run__source_type="sap_mb51")),
            utility_count=Count("id", filter=Q(ingestion_run__source_type="utility")),
            travel_count=Count("id", filter=Q(ingestion_run__source_type="travel")),
        )

        return Response(
            {
                "kg_co2e_by_scope": {
                    "1": str(summary["scope_1_kg_co2e"]),
                    "2": str(summary["scope_2_kg_co2e"]),
                    "3": str(summary["scope_3_kg_co2e"]),
                },
                "review_status_counts": {
                    "pending": summary["pending_count"],
                    "approved": summary["approved_count"],
                    "flagged": summary["flagged_count"],
                    "locked": summary["locked_count"],
                },
                "source_type_counts": {
                    "sap_mb51": summary["sap_mb51_count"],
                    "utility": summary["utility_count"],
                    "travel": summary["travel_count"],
                },
            }
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _guess_raw_key(raw_data: dict, activity_type: str, field_hint: str) -> str | None:
    """
    Given a raw_data dict and a field hint, try to find the matching key
    in the raw data. This handles the fact that different parsers use
    different internal key names.

    Returns the raw key name, or None if not found.
    """
    # Map from field hints to possible raw_data keys
    key_candidates = {
        "value": [
            "consumption_kwh", "quantity", "distance_km", "nights",
            "original_value", "kwh", "amount",
        ],
        "cost_center": [
            "cost_center", "cost_centre", "KOSTL",
        ],
        "facility_code": [
            "meter_id", "plant_code", "facility_code", "origin",
        ],
        "vendor": [
            "vendor", "vendor_name", "vendor_id", "supplier",
        ],
    }

    candidates = key_candidates.get(field_hint, [field_hint])
    for candidate in candidates:
        if candidate in raw_data:
            return candidate
    return None

