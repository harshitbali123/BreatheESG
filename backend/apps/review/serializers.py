from rest_framework import serializers

from apps.normalization.models import NormalizedActivity


class NormalizedActivityListSerializer(serializers.ModelSerializer):
    ingestion_run_id = serializers.CharField(source="ingestion_run.id", read_only=True)
    source_type = serializers.CharField(source="ingestion_run.source_type", read_only=True)
    source_type_display = serializers.CharField(
        source="ingestion_run.get_source_type_display",
        read_only=True,
    )
    review_status_display = serializers.CharField(
        source="get_review_status_display",
        read_only=True,
    )
    activity_type_display = serializers.CharField(
        source="get_activity_type_display",
        read_only=True,
    )

    class Meta:
        model = NormalizedActivity
        fields = [
            "id",
            "tenant",
            "ingestion_run_id",
            "source_type",
            "source_type_display",
            "activity_type",
            "activity_type_display",
            "activity_date",
            "period_end",
            "description",
            "facility_code",
            "facility_name",
            "country_code",
            "cost_center",
            "vendor",
            "scope",
            "scope3_category",
            "original_value",
            "original_unit",
            "original_currency",
            "original_amount",
            "normalized_kg_co2e",
            "emission_factor_used",
            "emission_factor_source",
            "review_status",
            "review_status_display",
            "reviewed_by",
            "reviewed_at",
            "review_note",
            "is_flagged_suspicious",
            "flag_reasons",
            "was_edited",
            "edited_by",
            "edited_at",
            "edit_note",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class ReviewActionSerializer(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True, allow_null=True)


class ActivityEditSerializer(serializers.Serializer):
    """
    Accepts editable fields for fixing flagged/warning activities.
    All fields are optional — only the ones the user provides will be updated.
    CO2 is recalculated automatically based on the new original_value.
    """
    original_value    = serializers.DecimalField(max_digits=18, decimal_places=4, required=False)
    original_unit     = serializers.CharField(max_length=20, required=False)
    original_amount   = serializers.DecimalField(max_digits=18, decimal_places=2, required=False, allow_null=True)
    original_currency = serializers.CharField(max_length=3, required=False, allow_blank=True)
    activity_date     = serializers.DateField(required=False)
    period_end        = serializers.DateField(required=False, allow_null=True)
    description       = serializers.CharField(max_length=500, required=False, allow_blank=True)
    facility_code     = serializers.CharField(max_length=50, required=False, allow_blank=True)
    facility_name     = serializers.CharField(max_length=255, required=False, allow_blank=True)
    cost_center       = serializers.CharField(max_length=50, required=False, allow_blank=True)
    vendor            = serializers.CharField(max_length=255, required=False, allow_blank=True)
    country_code      = serializers.CharField(max_length=2, required=False, allow_blank=True)
    cabin_class       = serializers.CharField(max_length=30, required=False, allow_blank=True)
    edit_note         = serializers.CharField(required=False, allow_blank=True, default="")
    clear_flags       = serializers.BooleanField(required=False, default=True)


class BulkApproveSerializer(serializers.Serializer):
    ids = serializers.ListField(
        child=serializers.UUIDField(),
        allow_empty=False,
    )
