"""
Ingestion views
===============

UploadView          POST /api/ingestion/upload/
IngestionRunViewSet GET  /api/ingestion/runs/
                    GET  /api/ingestion/runs/:id/

Design notes
------------
- Parsing is SYNCHRONOUS in this prototype. The file is parsed in the same
  request/response cycle. For a production system you'd push to Celery and
  return a run ID immediately; that's noted in TRADEOFFS.md.

- The upload view does five things in order:
    1. Validate the incoming request (serializer)
    2. Hash the file and check for duplicates
    3. Create an IngestionRun record (status=PENDING)
    4. Dispatch to the right parser
    5. Update the run status and return the result

- If the parser raises an unhandled exception, the run is marked FAILED
  and the exception message is stored on error_message. The request returns
  HTTP 422 with a structured error body so the frontend can show the user
  something useful rather than a 500.

- Every upload action writes an AuditLog entry regardless of outcome.
"""

import hashlib
import logging
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.models import AuditLog
from .models import IngestionRun, RawRow
from .serializers import (
    UploadSerializer,
    IngestionRunSerializer,
    IngestionRunListSerializer,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sha256(file_obj) -> str:
    """
    Stream the file through SHA-256 in 8KB chunks.
    Resets the file pointer to 0 afterwards so the parser can read it.
    """
    h = hashlib.sha256()
    file_obj.seek(0)
    for chunk in iter(lambda: file_obj.read(8192), b""):
        h.update(chunk)
    file_obj.seek(0)
    return h.hexdigest()


def _get_client_ip(request) -> str:
    """Extract the real client IP, respecting X-Forwarded-For if present."""
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def _write_audit(tenant, actor, action, target_id, detail,
                 before=None, after=None, ip=None):
    """Single call-site for writing audit log entries from this module."""
    AuditLog.objects.create(
        tenant=tenant,
        actor=actor,
        action=action,
        target_type="ingestion_run",
        target_id=target_id,
        before_state=before,
        after_state=after,
        detail=detail,
        ip_address=ip,
    )


# ---------------------------------------------------------------------------
# Parser dispatch registry
# ---------------------------------------------------------------------------
# Parsers are imported lazily (inside the function) to avoid circular imports
# on startup. Each parser module must expose a single function:
#   parse(run: IngestionRun, file_obj) -> dict
# returning {"success": int, "failed": int, "flagged": int}

def _dispatch(source_type: str, run: IngestionRun, file_obj):
    """
    Route to the correct parser based on source_type.
    Returns the counts dict from the parser.
    Raises ImportError if a parser module hasn't been written yet —
    that surfaces as a clean 422 rather than a 500.
    """
    if source_type == IngestionRun.SourceType.SAP_MB51:
        from .parsers.sap_mb51 import parse
    elif source_type == IngestionRun.SourceType.UTILITY:
        from .parsers.utility import parse
    elif source_type == IngestionRun.SourceType.TRAVEL:
        from .parsers.travel import parse
    else:
        raise ValueError(f"No parser registered for source_type '{source_type}'.")

    return parse(run, file_obj)


# ---------------------------------------------------------------------------
# Upload view
# ---------------------------------------------------------------------------

class UploadView(APIView):
    """
    POST /api/ingestion/upload/

    Accepts multipart/form-data with:
        file           — the data file
        source_type    — "sap_mb51" | "utility" | "travel"
        reporting_year — optional int (e.g. 2024)

    Returns HTTP 201 on success with the full IngestionRun object.
    Returns HTTP 409 if this exact file has already been uploaded.
    Returns HTTP 422 if parsing fails (run is saved with status=FAILED).
    """
    parser_classes  = [MultiPartParser, FormParser]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        tenant = request.user.tenant
        if tenant is None:
            return Response(
                {"detail": "Your account is not associated with a tenant."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # ── Step 1: Validate the request ──────────────────────────────────
        serializer = UploadSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"detail": "Invalid upload request.", "errors": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        file           = serializer.validated_data["file"]
        source_type    = serializer.validated_data["source_type"]
        reporting_year = serializer.validated_data.get("reporting_year")

        # ── Step 2: Hash the file, check for duplicates ───────────────────
        file_hash = _sha256(file)
        ip        = _get_client_ip(request)

        existing = IngestionRun.objects.filter(
            tenant=tenant,
            file_hash_sha256=file_hash,
        ).order_by("-created_at").first()

        if existing:
            logger.info(
                "Duplicate upload detected: tenant=%s hash=%s existing_run=%s",
                tenant.slug, file_hash[:8], existing.id,
            )
            return Response(
                {
                    "detail": (
                        "This file has already been uploaded. "
                        "If you intended to re-process it, use the re-run endpoint."
                    ),
                    "duplicate_of": {
                        "run_id":    str(existing.id),
                        "filename":  existing.original_filename,
                        "uploaded_at": existing.created_at.isoformat(),
                        "status":    existing.status,
                    },
                },
                status=status.HTTP_409_CONFLICT,
            )

        # ── Step 3: Create the IngestionRun record ────────────────────────
        run = IngestionRun.objects.create(
            tenant=tenant,
            source_type=source_type,
            status=IngestionRun.Status.PROCESSING,
            original_filename=file.name,
            file_hash_sha256=file_hash,
            uploaded_by=request.user,
            reporting_year=reporting_year,
        )

        _write_audit(
            tenant=tenant,
            actor=request.user,
            action=AuditLog.Action.INGESTION_STARTED,
            target_id=run.id,
            detail=f"Upload started: {file.name} ({file.size} bytes), source={source_type}",
            ip=ip,
        )

        logger.info(
            "Ingestion run created: id=%s tenant=%s source=%s file=%s",
            run.id, tenant.slug, source_type, file.name,
        )

        # ── Step 4: Dispatch to parser ────────────────────────────────────
        try:
            counts = _dispatch(source_type, run, file)

        except ImportError as exc:
            # Parser module not yet implemented
            _mark_failed(run, f"Parser not implemented: {exc}")
            _write_audit(
                tenant=tenant, actor=request.user,
                action=AuditLog.Action.INGESTION_FAILED,
                target_id=run.id,
                detail=f"Parser not implemented for '{source_type}'.",
                ip=ip,
            )
            return Response(
                {
                    "detail": f"Parser for '{source_type}' is not yet implemented.",
                    "run_id": str(run.id),
                },
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        except Exception as exc:
            # Unexpected parser failure — record it, don't crash the process
            error_msg = f"{type(exc).__name__}: {exc}"
            logger.exception(
                "Parser failed: run=%s source=%s error=%s",
                run.id, source_type, error_msg,
            )
            _mark_failed(run, error_msg)
            _write_audit(
                tenant=tenant, actor=request.user,
                action=AuditLog.Action.INGESTION_FAILED,
                target_id=run.id,
                detail=f"Parser raised an exception: {error_msg}",
                ip=ip,
            )
            return Response(
                {
                    "detail": "The file could not be parsed. See error_message for details.",
                    "run_id":        str(run.id),
                    "error_message": error_msg,
                },
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        # ── Step 5: Mark the run complete and return ──────────────────────
        run.status            = IngestionRun.Status.COMPLETED
        run.row_count_success = counts.get("success", 0)
        run.row_count_failed  = counts.get("failed", 0)
        run.row_count_flagged = counts.get("flagged", 0)
        run.row_count_total   = (
            run.row_count_success + run.row_count_failed
        )
        run.completed_at = timezone.now()
        run.save(update_fields=[
            "status", "row_count_total", "row_count_success",
            "row_count_failed", "row_count_flagged", "completed_at",
        ])

        _write_audit(
            tenant=tenant, actor=request.user,
            action=AuditLog.Action.INGESTION_COMPLETED,
            target_id=run.id,
            detail=(
                f"Completed: {run.row_count_total} rows total, "
                f"{run.row_count_success} OK, "
                f"{run.row_count_failed} failed, "
                f"{run.row_count_flagged} flagged."
            ),
            after={
                "status":    run.status,
                "success":   run.row_count_success,
                "failed":    run.row_count_failed,
                "flagged":   run.row_count_flagged,
            },
            ip=ip,
        )

        logger.info(
            "Ingestion run completed: id=%s total=%d ok=%d failed=%d flagged=%d",
            run.id, run.row_count_total,
            run.row_count_success, run.row_count_failed, run.row_count_flagged,
        )

        return Response(
            IngestionRunSerializer(run).data,
            status=status.HTTP_201_CREATED,
        )


def _mark_failed(run: IngestionRun, message: str):
    """Utility: flip a run to FAILED and store the error message."""
    run.status        = IngestionRun.Status.FAILED
    run.error_message = message
    run.completed_at  = timezone.now()
    run.save(update_fields=["status", "error_message", "completed_at"])


# ---------------------------------------------------------------------------
# IngestionRun viewset  (list + retrieve only — no create/update/delete)
# ---------------------------------------------------------------------------

class IngestionRunViewSet(viewsets.ReadOnlyModelViewSet):
    """
    GET /api/ingestion/runs/        — list all runs for the current tenant
    GET /api/ingestion/runs/:id/    — run detail with nested raw rows
    GET /api/ingestion/runs/:id/raw-rows/  — raw rows for a run

    Tenant scoping is applied in get_queryset — analysts can only ever see
    their own tenant's data regardless of the URL they request.
    """
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """
        Always filter by the authenticated user's tenant.
        This is the critical security gate — never remove this filter.
        """
        qs = IngestionRun.objects.filter(
            tenant=self.request.user.tenant
        ).order_by("-created_at")

        # Optional filter: ?source_type=sap_mb51
        source_type = self.request.query_params.get("source_type")
        if source_type:
            qs = qs.filter(source_type=source_type)

        # Optional filter: ?status=completed
        run_status = self.request.query_params.get("status")
        if run_status:
            qs = qs.filter(status=run_status)

        return qs

    def get_serializer_class(self):
        # List view: lightweight (no nested rows)
        # Detail view: full with nested raw rows
        if self.action == "retrieve":
            return IngestionRunSerializer
        return IngestionRunListSerializer

    @action(detail=True, methods=["get"], url_path="raw-rows")
    def raw_rows(self, request, pk=None):
        """
        GET /api/ingestion/runs/:id/raw-rows/
        Returns all raw rows for a run, with optional parse_status filter.
        ?parse_status=failed  — show only failed rows
        ?parse_status=warning — show only warned rows
        """
        from rest_framework.pagination import PageNumberPagination
        from .serializers import RawRowSerializer

        run = self.get_object()  # already tenant-scoped via get_queryset
        rows = RawRow.objects.filter(
            ingestion_run=run
        ).order_by("row_number")

        parse_status = request.query_params.get("parse_status")
        if parse_status:
            rows = rows.filter(parse_status=parse_status)

        paginator = PageNumberPagination()
        paginator.page_size = 100
        page = paginator.paginate_queryset(rows, request)
        serializer = RawRowSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)