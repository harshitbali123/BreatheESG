"""
Ingestion serializers
=====================
UploadSerializer   — validates the incoming multipart request
IngestionRunSerializer — read-only representation returned to the client
RawRowSerializer   — nested inside run detail
"""

from rest_framework import serializers
from .models import IngestionRun, RawRow


ALLOWED_EXTENSIONS = {
    "sap_mb51": [".txt", ".csv", ".tsv"],
    "utility":  [".csv"],
    "travel":   [".csv"],
}

MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB


class UploadSerializer(serializers.Serializer):
    """
    Validates the two fields that must arrive in every upload request.
    source_type drives which parser runs and which file extensions are allowed.
    """
    file        = serializers.FileField()
    source_type = serializers.ChoiceField(choices=IngestionRun.SourceType.choices)
    reporting_year = serializers.IntegerField(
        required=False, allow_null=True,
        min_value=2000, max_value=2100,
        help_text="Optional. The reporting year this data covers.",
    )

    def validate(self, data):
        file        = data["file"]
        source_type = data["source_type"]

        # ── Size check ────────────────────────────────────────────────────
        if file.size > MAX_FILE_SIZE_BYTES:
            raise serializers.ValidationError(
                f"File exceeds the 10 MB limit ({file.size / 1024 / 1024:.1f} MB uploaded)."
            )

        # ── Extension check ───────────────────────────────────────────────
        import os
        ext = os.path.splitext(file.name)[1].lower()
        allowed = ALLOWED_EXTENSIONS.get(source_type, [])
        if ext not in allowed:
            raise serializers.ValidationError(
                f"'{ext}' is not a valid extension for source type '{source_type}'. "
                f"Expected one of: {', '.join(allowed)}"
            )

        return data


class RawRowSerializer(serializers.ModelSerializer):
    class Meta:
        model  = RawRow
        fields = [
            "id", "row_number", "raw_data",
            "parse_status", "parse_errors", "created_at",
        ]


class IngestionRunSerializer(serializers.ModelSerializer):
    """
    Full run representation including nested raw rows.
    Used in the run-detail endpoint. The list endpoint uses
    IngestionRunListSerializer (lighter, no nested rows).
    """
    raw_rows    = RawRowSerializer(many=True, read_only=True)
    uploaded_by = serializers.StringRelatedField()

    class Meta:
        model  = IngestionRun
        fields = [
            "id", "source_type", "status",
            "original_filename", "file_hash_sha256",
            "uploaded_by", "reporting_year",
            "row_count_total", "row_count_success",
            "row_count_failed", "row_count_flagged",
            "error_message",
            "created_at", "completed_at",
            "raw_rows",
        ]
        read_only_fields = fields


class IngestionRunListSerializer(serializers.ModelSerializer):
    """
    Lightweight version for the list endpoint — no nested rows.
    """
    uploaded_by = serializers.StringRelatedField()
    source_type_display = serializers.CharField(
        source="get_source_type_display", read_only=True)
    status_display = serializers.CharField(
        source="get_status_display", read_only=True)

    class Meta:
        model  = IngestionRun
        fields = [
            "id", "source_type", "source_type_display",
            "status", "status_display",
            "original_filename", "uploaded_by",
            "reporting_year",
            "row_count_total", "row_count_success",
            "row_count_failed", "row_count_flagged",
            "created_at", "completed_at",
        ]
        read_only_fields = fields