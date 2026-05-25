import uuid
from django.db import models
from django.utils import timezone
from apps.tenants.models import Tenant, User

def _uuid(): return uuid.uuid4()

class AuditLog(models.Model):
    class Action(models.TextChoices):
        INGESTION_STARTED   = "ingestion_started",   "Ingestion started"
        INGESTION_COMPLETED = "ingestion_completed",  "Ingestion completed"
        INGESTION_FAILED    = "ingestion_failed",     "Ingestion failed"
        ROW_PARSE_FAILED    = "row_parse_failed",     "Row parse failed"
        ACTIVITY_CREATED    = "activity_created",     "Activity created"
        ACTIVITY_APPROVED   = "activity_approved",    "Activity approved"
        ACTIVITY_FLAGGED    = "activity_flagged",     "Activity flagged"
        ACTIVITY_EDITED     = "activity_edited",      "Activity edited"
        ACTIVITY_LOCKED     = "activity_locked",      "Activity locked"
        BULK_APPROVED       = "bulk_approved",        "Bulk approval"

    id          = models.UUIDField(primary_key=True, default=_uuid, editable=False)
    tenant      = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="audit_logs")
    actor       = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    action      = models.CharField(max_length=40, choices=Action.choices)
    timestamp   = models.DateTimeField(default=timezone.now, db_index=True)
    target_type = models.CharField(max_length=40, blank=True)
    target_id   = models.UUIDField(null=True, blank=True)
    before_state = models.JSONField(null=True, blank=True)
    after_state  = models.JSONField(null=True, blank=True)
    detail       = models.TextField(blank=True)
    ip_address   = models.GenericIPAddressField(null=True, blank=True)

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValueError("AuditLog is append-only.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("AuditLog records cannot be deleted.")

    class Meta:
        db_table = "audit_log"
        ordering = ["-timestamp"]
        indexes  = [
            models.Index(fields=["tenant", "timestamp"]),
            models.Index(fields=["target_type", "target_id"]),
        ]
