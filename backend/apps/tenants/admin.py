from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import Tenant, User, PlantLookup

@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "country_code", "is_active"]

@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ["username", "email", "tenant", "role", "is_staff"]
    fieldsets = BaseUserAdmin.fieldsets + (
        ("BreatheESG", {"fields": ("tenant", "role")}),
    )

@admin.register(PlantLookup)
class PlantLookupAdmin(admin.ModelAdmin):
    list_display = ["plant_code", "plant_name", "country_code", "tenant"]
