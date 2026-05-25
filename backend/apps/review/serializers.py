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


class BulkApproveSerializer(serializers.Serializer):
    ids = serializers.ListField(
        child=serializers.UUIDField(),
        allow_empty=False,
    )
