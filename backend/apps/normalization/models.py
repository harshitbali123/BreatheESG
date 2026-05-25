import uuid
from django.db import models
from django.utils import timezone
from apps.tenants.models import Tenant, User
from apps.ingestion.models import IngestionRun, RawRow

def _uuid(): return uuid.uuid4()

class EmissionFactor(models.Model):
    class FuelType(models.TextChoices):
        DIESEL        = "diesel",       "Diesel"
        LPG           = "lpg",          "LPG / Propane"
        NATURAL_GAS   = "natural_gas",  "Natural Gas"
        HEATING_OIL   = "heating_oil",  "Heating Oil"
        ELECTRICITY   = "electricity",  "Electricity"
        FLIGHT_ECO    = "flight_eco",   "Flight — Economy"
        FLIGHT_BUS    = "flight_bus",   "Flight — Business"
        FLIGHT_FIRST  = "flight_first", "Flight — First"
        HOTEL         = "hotel",        "Hotel — per night"
        CAR           = "car",          "Car — per km"
        TRAIN         = "train",        "Train — per km"
    id               = models.UUIDField(primary_key=True, default=_uuid, editable=False)
    fuel_type        = models.CharField(max_length=30, choices=FuelType.choices)
    unit             = models.CharField(max_length=20)
    kg_co2e_per_unit = models.DecimalField(max_digits=18, decimal_places=8)
    source           = models.CharField(max_length=255)
    valid_from_year  = models.IntegerField()
    valid_to_year    = models.IntegerField(null=True, blank=True)
    notes            = models.TextField(blank=True)
    class Meta: db_table = "emission_factor"

class NormalizedActivity(models.Model):
    class Scope(models.TextChoices):
        SCOPE_1 = "1", "Scope 1"
        SCOPE_2 = "2", "Scope 2"
        SCOPE_3 = "3", "Scope 3"

    class ActivityType(models.TextChoices):
        DIESEL           = "diesel",          "Diesel"
        LPG              = "lpg",             "LPG"
        HEATING_OIL      = "heating_oil",     "Heating Oil"
        ELECTRICITY      = "electricity",     "Electricity"
        FLIGHT           = "flight",          "Flight"
        HOTEL            = "hotel",           "Hotel"
        GROUND_TRANSPORT = "ground_transport","Ground Transport"
        OTHER            = "other",           "Other"

    class ReviewStatus(models.TextChoices):
        PENDING  = "pending",  "Pending"
        APPROVED = "approved", "Approved"
        FLAGGED  = "flagged",  "Flagged"
        LOCKED   = "locked",   "Locked"

    id            = models.UUIDField(primary_key=True, default=_uuid, editable=False)
    tenant        = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="activities")
    ingestion_run = models.ForeignKey(IngestionRun, on_delete=models.PROTECT, related_name="activities")
    raw_row       = models.OneToOneField(RawRow, on_delete=models.PROTECT, related_name="activity")

    activity_type   = models.CharField(max_length=30, choices=ActivityType.choices)
    activity_date   = models.DateField()
    period_end      = models.DateField(null=True, blank=True)
    description     = models.CharField(max_length=500, blank=True)
    facility_code   = models.CharField(max_length=50, blank=True)
    facility_name   = models.CharField(max_length=255, blank=True)
    country_code    = models.CharField(max_length=2, blank=True)
    cost_center     = models.CharField(max_length=50, blank=True)
    vendor          = models.CharField(max_length=255, blank=True)

    scope           = models.CharField(max_length=1, choices=Scope.choices)
    scope3_category = models.IntegerField(null=True, blank=True)

    # Source values — immutable after creation
    original_value    = models.DecimalField(max_digits=18, decimal_places=4)
    original_unit     = models.CharField(max_length=20)
    original_currency = models.CharField(max_length=3, blank=True)
    original_amount   = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)

    # Normalized emission output
    normalized_kg_co2e     = models.DecimalField(max_digits=18, decimal_places=6)
    emission_factor_used   = models.DecimalField(max_digits=18, decimal_places=8)
    emission_factor_source = models.CharField(max_length=255, blank=True)

    # Review workflow
    review_status = models.CharField(max_length=20, choices=ReviewStatus.choices, default=ReviewStatus.PENDING)
    reviewed_by   = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                       related_name="reviewed_activities")
    reviewed_at   = models.DateTimeField(null=True, blank=True)
    review_note   = models.TextField(blank=True)

    # Suspicion flags
    is_flagged_suspicious = models.BooleanField(default=False)
    flag_reasons          = models.JSONField(default=list)

    # Edit tracking
    was_edited = models.BooleanField(default=False)
    edited_by  = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="edited_activities")
    edited_at  = models.DateTimeField(null=True, blank=True)
    edit_note  = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if self.pk:
            prev = NormalizedActivity.objects.filter(pk=self.pk).values("review_status").first()
            if prev and prev["review_status"] == self.ReviewStatus.LOCKED:
                raise ValueError(f"Record {self.pk} is locked for audit and cannot be modified.")
        super().save(*args, **kwargs)

    class Meta:
        db_table = "normalized_activity"
        ordering = ["-activity_date"]
        indexes  = [
            models.Index(fields=["tenant", "scope"]),
            models.Index(fields=["tenant", "review_status"]),
            models.Index(fields=["tenant", "activity_date"]),
        ]
