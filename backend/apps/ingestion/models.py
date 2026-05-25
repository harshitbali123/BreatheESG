import uuid
from django.db import models
from apps.tenants.models import Tenant, User

def _uuid(): return uuid.uuid4()

class IngestionRun(models.Model):
    class SourceType(models.TextChoices):
        SAP_MB51 = "sap_mb51", "SAP MB51 Flat File"
        UTILITY  = "utility",  "Utility Portal CSV"
        TRAVEL   = "travel",   "Corporate Travel CSV"

    class Status(models.TextChoices):
        PENDING    = "pending",    "Pending"
        PROCESSING = "processing", "Processing"
        COMPLETED  = "completed",  "Completed"
        FAILED     = "failed",     "Failed"

    id                 = models.UUIDField(primary_key=True, default=_uuid, editable=False)
    tenant             = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="ingestion_runs")
    source_type        = models.CharField(max_length=30, choices=SourceType.choices)
    status             = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    original_filename  = models.CharField(max_length=500, blank=True)
    file_hash_sha256   = models.CharField(max_length=64, blank=True)
    uploaded_by        = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    row_count_total    = models.IntegerField(default=0)
    row_count_success  = models.IntegerField(default=0)
    row_count_failed   = models.IntegerField(default=0)
    row_count_flagged  = models.IntegerField(default=0)
    reporting_year     = models.IntegerField(null=True, blank=True)
    error_message      = models.TextField(blank=True)
    created_at         = models.DateTimeField(auto_now_add=True)
    completed_at       = models.DateTimeField(null=True, blank=True)

    def __str__(self): return f"{self.source_type} | {self.created_at:%Y-%m-%d} | {self.status}"
    class Meta:
        db_table = "ingestion_run"
        ordering = ["-created_at"]

class RawRow(models.Model):
    class ParseStatus(models.TextChoices):
        OK      = "ok",      "OK"
        WARNING = "warning", "Warning"
        FAILED  = "failed",  "Failed"

    id            = models.UUIDField(primary_key=True, default=_uuid, editable=False)
    tenant        = models.ForeignKey(Tenant, on_delete=models.PROTECT)
    ingestion_run = models.ForeignKey(IngestionRun, on_delete=models.PROTECT, related_name="raw_rows")
    row_number    = models.IntegerField()
    raw_data      = models.JSONField()
    parse_status  = models.CharField(max_length=20, choices=ParseStatus.choices, default=ParseStatus.OK)
    parse_errors  = models.JSONField(default=list)
    created_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table        = "raw_row"
        unique_together = [("ingestion_run", "row_number")]
        ordering        = ["row_number"]
