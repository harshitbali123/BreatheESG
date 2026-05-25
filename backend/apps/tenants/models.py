import uuid
from django.db import models
from django.contrib.auth.models import AbstractUser

def _uuid(): return uuid.uuid4()

class Tenant(models.Model):
    id           = models.UUIDField(primary_key=True, default=_uuid, editable=False)
    name         = models.CharField(max_length=255)
    slug         = models.SlugField(max_length=100, unique=True)
    country_code = models.CharField(max_length=2)
    timezone     = models.CharField(max_length=64, default="UTC")
    grid_emission_factor_kg_per_kwh = models.DecimalField(
        max_digits=10, decimal_places=6, default=0.233)
    is_active    = models.BooleanField(default=True)
    created_at   = models.DateTimeField(auto_now_add=True)

    def __str__(self): return self.name
    class Meta: db_table = "tenant"

class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN   = "admin",   "Admin"
        ANALYST = "analyst", "Analyst"
        VIEWER  = "viewer",  "Viewer"
    id     = models.UUIDField(primary_key=True, default=_uuid, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT,
                               related_name="users", null=True, blank=True)
    role   = models.CharField(max_length=20, choices=Role.choices, default=Role.ANALYST)
    class Meta: db_table = "auth_user_extended"

class PlantLookup(models.Model):
    id           = models.UUIDField(primary_key=True, default=_uuid, editable=False)
    tenant       = models.ForeignKey(Tenant, on_delete=models.PROTECT)
    plant_code   = models.CharField(max_length=10)
    plant_name   = models.CharField(max_length=255)
    country_code = models.CharField(max_length=2)
    city         = models.CharField(max_length=100, blank=True)
    class Meta:
        db_table        = "plant_lookup"
        unique_together = [("tenant", "plant_code")]
