"""
Management command: seed_dev
============================
Populates the database with realistic development data:
  - 1 Tenant  (Demo Client Ltd)
  - 1 admin User  +  1 analyst User
  - 3 IngestionRuns  (one per source type)
  - 15 RawRows       (5 per run)
  - 15 NormalizedActivity rows  (5 per run, mixed review statuses)
  - 9  EmissionFactor rows      (DEFRA 2023 values)
  - 4  PlantLookup rows         (SAP plant codes)
  - AuditLog entries for every action

Usage
-----
    python manage.py seed_dev              # safe: skips if tenant already exists
    python manage.py seed_dev --flush      # drops all seeded data first
    python manage.py seed_dev --flush --quiet

Why this data looks the way it does
-------------------------------------
SAP rows: mixed units (L / KG), German column names, DD.MM.YYYY dates,
  one row with a missing cost centre (KOSTL blank), one outlier value
  that the suspicion-flag logic should catch.

Utility rows: billing periods that cross month boundaries, two different
  meters at the same site, one row with a mismatched tariff code.

Travel rows: flights identified by IATA codes only (no distance in source),
  hotel nights, one ground-transport row, one row with missing cabin class —
  all realistic Concur export quirks.
"""

import hashlib
import json
from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.tenants.models import Tenant, User, PlantLookup
from apps.ingestion.models import IngestionRun, RawRow
from apps.normalization.models import NormalizedActivity, EmissionFactor
from apps.audit.models import AuditLog


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_hash(label: str) -> str:
    """Deterministic SHA-256 stand-in for a real file hash."""
    return hashlib.sha256(label.encode()).hexdigest()


def _log(tenant, actor, action, target_type, target_id, detail, before=None, after=None):
    AuditLog.objects.create(
        tenant=tenant,
        actor=actor,
        action=action,
        target_type=target_type,
        target_id=target_id,
        before_state=before,
        after_state=after,
        detail=detail,
        ip_address="127.0.0.1",
    )


# ---------------------------------------------------------------------------
# Emission factors  (DEFRA 2023)
# Source: https://www.gov.uk/government/publications/
#         greenhouse-gas-reporting-conversion-factors-2023
# ---------------------------------------------------------------------------

EMISSION_FACTORS = [
    dict(fuel_type="diesel",       unit="L",     kg_co2e_per_unit=Decimal("2.68890"),
         source="DEFRA 2023", valid_from_year=2023,
         notes="Includes WTT. Diesel for road vehicles."),
    dict(fuel_type="lpg",          unit="KG",    kg_co2e_per_unit=Decimal("2.93300"),
         source="DEFRA 2023", valid_from_year=2023,
         notes="LPG / Propane, combustion + WTT."),
    dict(fuel_type="heating_oil",  unit="L",     kg_co2e_per_unit=Decimal("2.54050"),
         source="DEFRA 2023", valid_from_year=2023,
         notes="Burning oil (kerosene / heating oil)."),
    dict(fuel_type="electricity",  unit="kWh",   kg_co2e_per_unit=Decimal("0.23314"),
         source="DEFRA 2023", valid_from_year=2023,
         notes="UK grid average, location-based."),
    dict(fuel_type="flight_eco",   unit="km",    kg_co2e_per_unit=Decimal("0.25500"),
         source="DEFRA 2023", valid_from_year=2023,
         notes="Economy class, per passenger-km, includes RFI factor 1.9."),
    dict(fuel_type="flight_bus",   unit="km",    kg_co2e_per_unit=Decimal("0.61480"),
         source="DEFRA 2023", valid_from_year=2023,
         notes="Business class, per passenger-km, includes RFI."),
    dict(fuel_type="hotel",        unit="night", kg_co2e_per_unit=Decimal("19.90000"),
         source="DEFRA 2023", valid_from_year=2023,
         notes="UK average hotel, per room-night."),
    dict(fuel_type="car",          unit="km",    kg_co2e_per_unit=Decimal("0.17050"),
         source="DEFRA 2023", valid_from_year=2023,
         notes="Average petrol car, per km."),
    dict(fuel_type="train",        unit="km",    kg_co2e_per_unit=Decimal("0.03549"),
         source="DEFRA 2023", valid_from_year=2023,
         notes="National rail average, per passenger-km."),
]


# ---------------------------------------------------------------------------
# Raw SAP MB51 rows  (what the parser would have received verbatim)
# ---------------------------------------------------------------------------

SAP_RAW_ROWS = [
    # Normal diesel receipt — plant DE01, litres
    {
        "Materialdokument": "5000012301", "Pos.": "1",
        "Buchungsdatum": "03.01.2024",   "Werk": "DE01",
        "Materialnummer": "DIES-001",    "Kurztext": "Dieselkraftstoff EN590",
        "Bewegungsart": "101",           "Menge": "12500",
        "Mengeneinheit": "L",            "Wert (HW)": "18625.00",
        "Währung": "EUR",                "Lieferant": "V-10042",
        "Lieferantenname": "Petroplus GmbH",
        "Einkaufsbeleg": "4500089231",   "Kostenstelle": "KOST-1000",
    },
    # LPG receipt in KG — different unit to test normalisation
    {
        "Materialdokument": "5000012308", "Pos.": "1",
        "Buchungsdatum": "14.02.2024",   "Werk": "DE01",
        "Materialnummer": "LPG-001",     "Kurztext": "Fluessiggas (LPG) Propan",
        "Bewegungsart": "101",           "Menge": "4200",
        "Mengeneinheit": "KG",           "Wert (HW)": "5166.00",
        "Währung": "EUR",                "Lieferant": "V-10088",
        "Lieferantenname": "Westfalen AG",
        "Einkaufsbeleg": "4500089502",   "Kostenstelle": "KOST-1100",
    },
    # Missing Kostenstelle — the parser flags this as a warning, not a failure
    {
        "Materialdokument": "5000012303", "Pos.": "1",
        "Buchungsdatum": "15.01.2024",   "Werk": "DE02",
        "Materialnummer": "DIES-002",    "Kurztext": "Dieselkraftstoff (Fass 200L)",
        "Bewegungsart": "101",           "Menge": "9800",
        "Mengeneinheit": "KG",           "Wert (HW)": "16758.00",
        "Währung": "EUR",                "Lieferant": "V-10055",
        "Lieferantenname": "Shell Deutschland GmbH",
        "Einkaufsbeleg": "4500089301",   "Kostenstelle": "",   # ← blank
    },
    # India plant — different currency, smaller volume
    {
        "Materialdokument": "5000012305", "Pos.": "1",
        "Buchungsdatum": "29.01.2024",   "Werk": "IN01",
        "Materialnummer": "DIES-003",    "Kurztext": "High Speed Diesel (HSD)",
        "Bewegungsart": "101",           "Menge": "8500",
        "Mengeneinheit": "L",            "Wert (HW)": "714000.00",
        "Währung": "INR",                "Lieferant": "V-20011",
        "Lieferantenname": "Bharat Petroleum Corp",
        "Einkaufsbeleg": "4500091001",   "Kostenstelle": "KOST-IN01",
    },
    # OUTLIER — 425,000 L at plant DE02 in one day: suspicion flag expected
    {
        "Materialdokument": "5000012311", "Pos.": "1",
        "Buchungsdatum": "28.02.2024",   "Werk": "DE02",
        "Materialnummer": "DIES-001",    "Kurztext": "Dieselkraftstoff EN590",
        "Bewegungsart": "101",           "Menge": "425000",   # ← outlier
        "Mengeneinheit": "L",            "Wert (HW)": "668750.00",
        "Währung": "EUR",                "Lieferant": "V-10042",
        "Lieferantenname": "Petroplus GmbH",
        "Einkaufsbeleg": "4500089560",   "Kostenstelle": "KOST-DE02",
    },
]


# ---------------------------------------------------------------------------
# Raw utility rows  (portal CSV export)
# ---------------------------------------------------------------------------

UTILITY_RAW_ROWS = [
    # Meter MET-001 — billing period crosses Jan/Feb boundary
    {
        "account_number": "ACC-4421", "meter_id": "MET-001",
        "service_address": "Hauptstrasse 12, Hamburg",
        "billing_period_start": "15.01.2024", "billing_period_end": "17.02.2024",
        "consumption_kwh": "18420", "demand_kw": "42.5",
        "amount": "3684.00", "currency": "EUR", "tariff_code": "HV-ToU",
    },
    # Meter MET-001 — next billing period
    {
        "account_number": "ACC-4421", "meter_id": "MET-001",
        "service_address": "Hauptstrasse 12, Hamburg",
        "billing_period_start": "17.02.2024", "billing_period_end": "18.03.2024",
        "consumption_kwh": "16890", "demand_kw": "40.1",
        "amount": "3378.00", "currency": "EUR", "tariff_code": "HV-ToU",
    },
    # Meter MET-002 — different tariff, same site
    {
        "account_number": "ACC-4421", "meter_id": "MET-002",
        "service_address": "Hauptstrasse 12, Hamburg",
        "billing_period_start": "01.01.2024", "billing_period_end": "31.01.2024",
        "consumption_kwh": "5240", "demand_kw": "18.2",
        "amount": "1048.00", "currency": "EUR", "tariff_code": "LV-Flat",
    },
    # India site — INR, different emission factor applies (IN grid)
    {
        "account_number": "ACC-7701", "meter_id": "MET-IN01",
        "service_address": "Pune Industrial Estate, Plot 14",
        "billing_period_start": "01.01.2024", "billing_period_end": "31.01.2024",
        "consumption_kwh": "31200", "demand_kw": "95.0",
        "amount": "249600.00", "currency": "INR", "tariff_code": "HT-1",
    },
    # Mismatched tariff code — parser flags as warning (unknown tariff)
    {
        "account_number": "ACC-4421", "meter_id": "MET-003",
        "service_address": "Lagerstrasse 5, Berlin",
        "billing_period_start": "01.02.2024", "billing_period_end": "29.02.2024",
        "consumption_kwh": "9870", "demand_kw": "31.0",
        "amount": "1974.00", "currency": "EUR", "tariff_code": "UNKNOWN-X",  # ← flag
    },
]


# ---------------------------------------------------------------------------
# Raw travel rows  (Concur-style CSV)
# ---------------------------------------------------------------------------

TRAVEL_RAW_ROWS = [
    # Flight — IATA codes only, business class
    {
        "trip_id": "T-20240115", "expense_type": "AIR",
        "travel_date": "15.01.2024",
        "origin": "FRA", "destination": "LHR",
        "cabin_class": "Business", "employee_id": "EMP-1042",
        "cost_center": "CC-SALES", "amount": "1240.00", "currency": "EUR",
        "vendor": "Lufthansa",
    },
    # Flight — economy, no cabin class in source (common Concur gap)
    {
        "trip_id": "T-20240118", "expense_type": "AIR",
        "travel_date": "18.01.2024",
        "origin": "BOM", "destination": "DEL",
        "cabin_class": "",   # ← missing — default to economy
        "employee_id": "EMP-2201",
        "cost_center": "CC-OPS", "amount": "8500.00", "currency": "INR",
        "vendor": "IndiGo",
    },
    # Hotel — nights, no distance calculation needed
    {
        "trip_id": "T-20240115", "expense_type": "HOTEL",
        "travel_date": "15.01.2024",
        "origin": "London", "destination": "",
        "cabin_class": "", "employee_id": "EMP-1042",
        "cost_center": "CC-SALES", "amount": "420.00", "currency": "GBP",
        "vendor": "Marriott Canary Wharf",
        "nights": "2",
    },
    # Ground transport — car, distance in km
    {
        "trip_id": "T-20240210", "expense_type": "CAR",
        "travel_date": "10.02.2024",
        "origin": "Hamburg Airport", "destination": "Hamburg HQ",
        "cabin_class": "", "employee_id": "EMP-3301",
        "cost_center": "",   # ← missing cost centre
        "amount": "65.00", "currency": "EUR",
        "vendor": "Sixt",
        "distance_km": "38",
    },
    # Long-haul flight — FRA → SIN, economy
    {
        "trip_id": "T-20240225", "expense_type": "AIR",
        "travel_date": "25.02.2024",
        "origin": "FRA", "destination": "SIN",
        "cabin_class": "Economy", "employee_id": "EMP-1042",
        "cost_center": "CC-SALES", "amount": "890.00", "currency": "EUR",
        "vendor": "Singapore Airlines",
    },
]


# ---------------------------------------------------------------------------
# IATA great-circle distances (km) — precomputed for sample data
# In real parser: haversine(lat1, lon1, lat2, lon2)
# ---------------------------------------------------------------------------

IATA_DISTANCES = {
    ("FRA", "LHR"): 654,
    ("BOM", "DEL"): 1150,
    ("FRA", "SIN"): 10220,
}


# ---------------------------------------------------------------------------
# Main command
# ---------------------------------------------------------------------------

class Command(BaseCommand):
    help = (
        "Seed the database with development data: 1 tenant, 3 ingestion runs, "
        "15 raw rows, 15 normalized activities, emission factors, plant lookups."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--flush",
            action="store_true",
            help="Delete all existing seeded data before re-seeding.",
        )
        parser.add_argument(
            "--quiet",
            action="store_true",
            help="Suppress progress output.",
        )

    # ------------------------------------------------------------------ #

    def handle(self, *args, **options):
        self.quiet = options["quiet"]

        if options["flush"]:
            self._flush()

        if Tenant.objects.filter(slug="demo-client").exists() and not options["flush"]:
            self.out("Tenant 'demo-client' already exists — skipping. "
                     "Use --flush to re-seed.")
            return

        self.out("── Seeding emission factors ───────────────────────────")
        factors = self._seed_emission_factors()

        self.out("── Seeding tenant + users ─────────────────────────────")
        tenant, admin_user, analyst_user = self._seed_tenant_and_users()

        self.out("── Seeding plant lookup ───────────────────────────────")
        self._seed_plant_lookup(tenant)

        self.out("── Seeding SAP MB51 ingestion run ─────────────────────")
        self._seed_sap_run(tenant, admin_user, analyst_user, factors)

        self.out("── Seeding utility ingestion run ──────────────────────")
        self._seed_utility_run(tenant, admin_user, analyst_user, factors)

        self.out("── Seeding travel ingestion run ───────────────────────")
        self._seed_travel_run(tenant, admin_user, analyst_user, factors)

        self.out("")
        self.out("════════════════════════════════════════════════════════")
        self.out("  Seed complete.")
        self.out(f"  Tenant  : Demo Client Ltd  (slug: demo-client)")
        self.out(f"  Admin   : admin@breatheesg.com  / breathe123")
        self.out(f"  Analyst : analyst@demo-client.com  / breathe123")
        self.out(f"  Runs    : {IngestionRun.objects.filter(tenant=tenant).count()}")
        self.out(f"  Raw rows: {RawRow.objects.filter(tenant=tenant).count()}")
        self.out(f"  Activities: {NormalizedActivity.objects.filter(tenant=tenant).count()}")
        self.out("════════════════════════════════════════════════════════")

    # ------------------------------------------------------------------ #
    # Flush
    # ------------------------------------------------------------------ #

    def _flush(self):
        self.out("── Flushing existing seed data ────────────────────────")
        tenant = Tenant.objects.filter(slug="demo-client").first()
        if tenant:
            # AuditLog has no delete(), so we bypass via queryset.delete()
            # which goes directly to SQL and skips our model-level guard.
            AuditLog.objects.filter(tenant=tenant).delete()
            NormalizedActivity.objects.filter(tenant=tenant).delete()
            RawRow.objects.filter(tenant=tenant).delete()
            IngestionRun.objects.filter(tenant=tenant).delete()
            PlantLookup.objects.filter(tenant=tenant).delete()
            User.objects.filter(tenant=tenant).delete()
            tenant.delete()
            self.out("   Tenant and all related data deleted.")
        EmissionFactor.objects.all().delete()
        self.out("   Emission factors deleted.")

    # ------------------------------------------------------------------ #
    # Emission factors
    # ------------------------------------------------------------------ #

    def _seed_emission_factors(self):
        factors = {}
        for f in EMISSION_FACTORS:
            obj, created = EmissionFactor.objects.get_or_create(
                fuel_type=f["fuel_type"],
                valid_from_year=f["valid_from_year"],
                defaults=f,
            )
            factors[f["fuel_type"]] = obj
            if created:
                self.out(f"   + EmissionFactor: {obj.fuel_type} "
                         f"({obj.kg_co2e_per_unit} kg CO₂e/{obj.unit})")
        return factors

    # ------------------------------------------------------------------ #
    # Tenant + users
    # ------------------------------------------------------------------ #

    def _seed_tenant_and_users(self):
        tenant = Tenant.objects.create(
            name="Demo Client Ltd",
            slug="demo-client",
            country_code="DE",
            timezone="Europe/Berlin",
            grid_emission_factor_kg_per_kwh=Decimal("0.23314"),
        )
        self.out(f"   + Tenant: {tenant.name}")

        admin_user = User.objects.create_superuser(
            username="admin",
            email="admin@breatheesg.com",
            password="breathe123",
        )
        admin_user.tenant = tenant
        admin_user.role = User.Role.ADMIN
        admin_user.save()
        self.out(f"   + User (admin):   admin / breathe123")

        analyst_user = User.objects.create_user(
            username="analyst",
            email="analyst@demo-client.com",
            password="breathe123",
        )
        analyst_user.tenant = tenant
        analyst_user.role = User.Role.ANALYST
        analyst_user.save()
        self.out(f"   + User (analyst): analyst / breathe123")

        return tenant, admin_user, analyst_user

    # ------------------------------------------------------------------ #
    # Plant lookup
    # ------------------------------------------------------------------ #

    def _seed_plant_lookup(self, tenant):
        plants = [
            dict(plant_code="DE01", plant_name="Hamburg Refinery",     country_code="DE", city="Hamburg"),
            dict(plant_code="DE02", plant_name="Berlin Distribution",   country_code="DE", city="Berlin"),
            dict(plant_code="IN01", plant_name="Pune Manufacturing",    country_code="IN", city="Pune"),
            dict(plant_code="1000", plant_name="Frankfurt HQ Facility", country_code="DE", city="Frankfurt"),
        ]
        for p in plants:
            PlantLookup.objects.create(tenant=tenant, **p)
            self.out(f"   + PlantLookup: {p['plant_code']} → {p['plant_name']}")

    # ------------------------------------------------------------------ #
    # SAP MB51 run
    # ------------------------------------------------------------------ #

    def _seed_sap_run(self, tenant, admin_user, analyst_user, factors):
        run = IngestionRun.objects.create(
            tenant=tenant,
            source_type=IngestionRun.SourceType.SAP_MB51,
            status=IngestionRun.Status.COMPLETED,
            original_filename="MB51_export_Q1_2024.txt",
            file_hash_sha256=_fake_hash("sap_mb51_q1_2024"),
            uploaded_by=admin_user,
            row_count_total=5,
            row_count_success=4,
            row_count_failed=0,
            row_count_flagged=1,
            reporting_year=2024,
            completed_at=timezone.now(),
        )
        _log(tenant, admin_user, AuditLog.Action.INGESTION_COMPLETED,
             "ingestion_run", run.id,
             f"Processed {run.original_filename}: 5 rows, 1 flagged.")
        self.out(f"   + IngestionRun: {run}")

        # Map material numbers → activity type + emission factor key + scope
        material_map = {
            "DIES-001": ("diesel",      "diesel",      "1", None),
            "DIES-002": ("diesel",      "diesel",      "1", None),
            "DIES-003": ("diesel",      "diesel",      "1", None),
            "LPG-001":  ("lpg",         "lpg",         "1", None),
            "HEL-001":  ("heating_oil", "heating_oil", "1", None),
        }

        # Unit conversion: KG diesel → L  (density ~0.84 kg/L)
        def to_factor_unit(value, unit, activity_type):
            if activity_type == "diesel" and unit == "KG":
                return Decimal(value) / Decimal("0.84"), "L"
            if activity_type == "diesel" and unit == "M3":
                return Decimal(value) * Decimal("1000"), "L"
            return Decimal(value), unit

        # Review statuses to assign — mix them for a realistic dashboard
        review_statuses = [
            NormalizedActivity.ReviewStatus.APPROVED,
            NormalizedActivity.ReviewStatus.PENDING,
            NormalizedActivity.ReviewStatus.FLAGGED,
            NormalizedActivity.ReviewStatus.LOCKED,
            NormalizedActivity.ReviewStatus.PENDING,
        ]

        for i, (raw_data, status) in enumerate(zip(SAP_RAW_ROWS, review_statuses), start=1):
            matnr       = raw_data["Materialnummer"]
            act_type, ef_key, scope, s3cat = material_map.get(
                matnr, ("other", "diesel", "1", None))

            raw_qty  = Decimal(raw_data["Menge"])
            raw_unit = raw_data["Mengeneinheit"]
            norm_qty, norm_unit = to_factor_unit(raw_qty, raw_unit, act_type)

            ef = factors[ef_key]
            kg_co2e = norm_qty * ef.kg_co2e_per_unit

            # Parse DD.MM.YYYY
            d, m, y = raw_data["Buchungsdatum"].split(".")
            act_date = date(int(y), int(m), int(d))

            is_outlier = float(raw_qty) > 100_000
            flag_reasons = []
            if is_outlier:
                flag_reasons.append("value_outlier: exceeds 100,000 L/KG in single receipt")
            if not raw_data.get("Kostenstelle"):
                flag_reasons.append("missing_cost_centre: KOSTL blank in source")

            parse_status = (RawRow.ParseStatus.WARNING
                            if flag_reasons else RawRow.ParseStatus.OK)

            raw_row = RawRow.objects.create(
                tenant=tenant,
                ingestion_run=run,
                row_number=i,
                raw_data=raw_data,
                parse_status=parse_status,
                parse_errors=flag_reasons,
            )

            reviewed_by = analyst_user if status in (
                NormalizedActivity.ReviewStatus.APPROVED,
                NormalizedActivity.ReviewStatus.LOCKED,
                NormalizedActivity.ReviewStatus.FLAGGED,
            ) else None
            reviewed_at = timezone.now() if reviewed_by else None

            activity = NormalizedActivity.objects.create(
                tenant=tenant,
                ingestion_run=run,
                raw_row=raw_row,
                activity_type=act_type,
                activity_date=act_date,
                description=raw_data["Kurztext"],
                facility_code=raw_data["Werk"],
                cost_center=raw_data.get("Kostenstelle", ""),
                vendor=raw_data.get("Lieferantenname", ""),
                scope=scope,
                scope3_category=s3cat,
                original_value=raw_qty,
                original_unit=raw_unit,
                original_currency=raw_data.get("Währung", ""),
                original_amount=Decimal(raw_data.get("Wert (HW)", "0")),
                normalized_kg_co2e=round(kg_co2e, 4),
                emission_factor_used=ef.kg_co2e_per_unit,
                emission_factor_source=ef.source,
                review_status=status,
                reviewed_by=reviewed_by,
                reviewed_at=reviewed_at,
                is_flagged_suspicious=bool(flag_reasons),
                flag_reasons=flag_reasons,
            )

            action = {
                NormalizedActivity.ReviewStatus.APPROVED: AuditLog.Action.ACTIVITY_APPROVED,
                NormalizedActivity.ReviewStatus.FLAGGED:  AuditLog.Action.ACTIVITY_FLAGGED,
                NormalizedActivity.ReviewStatus.LOCKED:   AuditLog.Action.ACTIVITY_LOCKED,
            }.get(status, AuditLog.Action.ACTIVITY_CREATED)

            _log(tenant, reviewed_by or admin_user, action,
                 "normalized_activity", activity.id,
                 f"{act_type.upper()} | {act_date} | "
                 f"{raw_qty} {raw_unit} → {activity.normalized_kg_co2e} kg CO₂e")

            self.out(f"   + Activity [{status:8}]: "
                     f"{act_type:12} {raw_qty:>10} {raw_unit:3} → "
                     f"{activity.normalized_kg_co2e:>12.2f} kg CO₂e"
                     + (" ⚑ flagged" if flag_reasons else ""))

    # ------------------------------------------------------------------ #
    # Utility run
    # ------------------------------------------------------------------ #

    def _seed_utility_run(self, tenant, admin_user, analyst_user, factors):
        run = IngestionRun.objects.create(
            tenant=tenant,
            source_type=IngestionRun.SourceType.UTILITY,
            status=IngestionRun.Status.COMPLETED,
            original_filename="utility_portal_export_2024-03.csv",
            file_hash_sha256=_fake_hash("utility_portal_2024_03"),
            uploaded_by=analyst_user,
            row_count_total=5,
            row_count_success=4,
            row_count_failed=0,
            row_count_flagged=1,
            reporting_year=2024,
            completed_at=timezone.now(),
        )
        _log(tenant, analyst_user, AuditLog.Action.INGESTION_COMPLETED,
             "ingestion_run", run.id, f"Processed {run.original_filename}")
        self.out(f"   + IngestionRun: {run}")

        ef = factors["electricity"]

        review_statuses = [
            NormalizedActivity.ReviewStatus.APPROVED,
            NormalizedActivity.ReviewStatus.APPROVED,
            NormalizedActivity.ReviewStatus.PENDING,
            NormalizedActivity.ReviewStatus.PENDING,
            NormalizedActivity.ReviewStatus.FLAGGED,
        ]

        for i, (raw_data, status) in enumerate(zip(UTILITY_RAW_ROWS, review_statuses), start=1):
            kwh = Decimal(raw_data["consumption_kwh"])
            kg_co2e = kwh * ef.kg_co2e_per_unit

            # Use billing_period_start as the activity date
            d, m, y = raw_data["billing_period_start"].split(".")
            act_date = date(int(y), int(m), int(d))

            d2, m2, y2 = raw_data["billing_period_end"].split(".")
            period_end = date(int(y2), int(m2), int(d2))

            flag_reasons = []
            if raw_data.get("tariff_code", "").startswith("UNKNOWN"):
                flag_reasons.append("unknown_tariff_code: tariff not in lookup table")

            parse_status = (RawRow.ParseStatus.WARNING
                            if flag_reasons else RawRow.ParseStatus.OK)

            raw_row = RawRow.objects.create(
                tenant=tenant,
                ingestion_run=run,
                row_number=i,
                raw_data=raw_data,
                parse_status=parse_status,
                parse_errors=flag_reasons,
            )

            reviewed_by = analyst_user if status in (
                NormalizedActivity.ReviewStatus.APPROVED,
                NormalizedActivity.ReviewStatus.FLAGGED,
            ) else None

            activity = NormalizedActivity.objects.create(
                tenant=tenant,
                ingestion_run=run,
                raw_row=raw_row,
                activity_type=NormalizedActivity.ActivityType.ELECTRICITY,
                activity_date=act_date,
                period_end=period_end,
                description=f"Electricity — {raw_data['meter_id']}",
                facility_code=raw_data["meter_id"],
                scope=NormalizedActivity.Scope.SCOPE_2,
                scope3_category=None,
                original_value=kwh,
                original_unit="kWh",
                original_currency=raw_data.get("currency", ""),
                original_amount=Decimal(raw_data.get("amount", "0")),
                normalized_kg_co2e=round(kg_co2e, 4),
                emission_factor_used=ef.kg_co2e_per_unit,
                emission_factor_source=ef.source,
                review_status=status,
                reviewed_by=reviewed_by,
                reviewed_at=timezone.now() if reviewed_by else None,
                is_flagged_suspicious=bool(flag_reasons),
                flag_reasons=flag_reasons,
            )

            action = {
                NormalizedActivity.ReviewStatus.APPROVED: AuditLog.Action.ACTIVITY_APPROVED,
                NormalizedActivity.ReviewStatus.FLAGGED:  AuditLog.Action.ACTIVITY_FLAGGED,
            }.get(status, AuditLog.Action.ACTIVITY_CREATED)

            _log(tenant, reviewed_by or admin_user, action,
                 "normalized_activity", activity.id,
                 f"Electricity | {act_date}→{period_end} | "
                 f"{kwh} kWh → {activity.normalized_kg_co2e} kg CO₂e")

            self.out(f"   + Activity [{status:8}]: "
                     f"electricity  {kwh:>10} kWh → "
                     f"{activity.normalized_kg_co2e:>12.2f} kg CO₂e"
                     + (" ⚑ flagged" if flag_reasons else ""))

    # ------------------------------------------------------------------ #
    # Travel run
    # ------------------------------------------------------------------ #

    def _seed_travel_run(self, tenant, admin_user, analyst_user, factors):
        run = IngestionRun.objects.create(
            tenant=tenant,
            source_type=IngestionRun.SourceType.TRAVEL,
            status=IngestionRun.Status.COMPLETED,
            original_filename="concur_travel_export_Q1_2024.csv",
            file_hash_sha256=_fake_hash("concur_travel_q1_2024"),
            uploaded_by=analyst_user,
            row_count_total=5,
            row_count_success=5,
            row_count_failed=0,
            row_count_flagged=1,
            reporting_year=2024,
            completed_at=timezone.now(),
        )
        _log(tenant, analyst_user, AuditLog.Action.INGESTION_COMPLETED,
             "ingestion_run", run.id, f"Processed {run.original_filename}")
        self.out(f"   + IngestionRun: {run}")

        review_statuses = [
            NormalizedActivity.ReviewStatus.APPROVED,
            NormalizedActivity.ReviewStatus.PENDING,
            NormalizedActivity.ReviewStatus.APPROVED,
            NormalizedActivity.ReviewStatus.FLAGGED,
            NormalizedActivity.ReviewStatus.PENDING,
        ]

        for i, (raw_data, status) in enumerate(zip(TRAVEL_RAW_ROWS, review_statuses), start=1):
            expense_type = raw_data["expense_type"]

            d, m, y = raw_data["travel_date"].split(".")
            act_date = date(int(y), int(m), int(d))

            flag_reasons = []
            if not raw_data.get("cost_center"):
                flag_reasons.append("missing_cost_centre")

            # --- Determine activity type, quantity, unit, emission factor ---
            if expense_type == "AIR":
                origin  = raw_data["origin"]
                dest    = raw_data["destination"]
                dist_km = IATA_DISTANCES.get((origin, dest), 0)

                cabin = (raw_data.get("cabin_class") or "").strip()
                if not cabin:
                    cabin = "Economy"
                    flag_reasons.append("missing_cabin_class: defaulted to Economy")

                ef_key   = "flight_bus" if cabin == "Business" else "flight_eco"
                ef       = factors[ef_key]
                qty      = Decimal(dist_km)
                unit     = "km"
                act_type = NormalizedActivity.ActivityType.FLIGHT
                desc     = f"Flight {origin}→{dest} ({cabin})"

            elif expense_type == "HOTEL":
                nights  = Decimal(raw_data.get("nights", "1"))
                ef      = factors["hotel"]
                qty     = nights
                unit    = "night"
                act_type = NormalizedActivity.ActivityType.HOTEL
                desc    = f"Hotel: {raw_data.get('vendor', '')} ({nights} nights)"

            elif expense_type == "CAR":
                dist_km = Decimal(raw_data.get("distance_km", "0"))
                ef      = factors["car"]
                qty     = dist_km
                unit    = "km"
                act_type = NormalizedActivity.ActivityType.GROUND_TRANSPORT
                desc    = f"Car hire: {raw_data.get('origin', '')} → {raw_data.get('destination', '')}"

            elif expense_type == "TRAIN":
                dist_km = Decimal(raw_data.get("distance_km", "0"))
                ef      = factors["train"]
                qty     = dist_km
                unit    = "km"
                act_type = NormalizedActivity.ActivityType.GROUND_TRANSPORT
                desc    = f"Train: {raw_data.get('origin', '')} → {raw_data.get('destination', '')}"

            else:
                ef      = factors["car"]
                qty     = Decimal("0")
                unit    = "km"
                act_type = NormalizedActivity.ActivityType.OTHER
                desc    = expense_type

            kg_co2e = qty * ef.kg_co2e_per_unit

            parse_status = (RawRow.ParseStatus.WARNING
                            if flag_reasons else RawRow.ParseStatus.OK)

            raw_row = RawRow.objects.create(
                tenant=tenant,
                ingestion_run=run,
                row_number=i,
                raw_data=raw_data,
                parse_status=parse_status,
                parse_errors=flag_reasons,
            )

            reviewed_by = analyst_user if status in (
                NormalizedActivity.ReviewStatus.APPROVED,
                NormalizedActivity.ReviewStatus.FLAGGED,
            ) else None

            activity = NormalizedActivity.objects.create(
                tenant=tenant,
                ingestion_run=run,
                raw_row=raw_row,
                activity_type=act_type,
                activity_date=act_date,
                description=desc,
                cost_center=raw_data.get("cost_center", ""),
                vendor=raw_data.get("vendor", ""),
                scope=NormalizedActivity.Scope.SCOPE_3,
                scope3_category=6,  # Business travel
                original_value=qty,
                original_unit=unit,
                original_currency=raw_data.get("currency", ""),
                original_amount=Decimal(raw_data.get("amount", "0")),
                normalized_kg_co2e=round(kg_co2e, 4),
                emission_factor_used=ef.kg_co2e_per_unit,
                emission_factor_source=ef.source,
                review_status=status,
                reviewed_by=reviewed_by,
                reviewed_at=timezone.now() if reviewed_by else None,
                is_flagged_suspicious=bool(flag_reasons),
                flag_reasons=flag_reasons,
            )

            action = {
                NormalizedActivity.ReviewStatus.APPROVED: AuditLog.Action.ACTIVITY_APPROVED,
                NormalizedActivity.ReviewStatus.FLAGGED:  AuditLog.Action.ACTIVITY_FLAGGED,
            }.get(status, AuditLog.Action.ACTIVITY_CREATED)

            _log(tenant, reviewed_by or admin_user, action,
                 "normalized_activity", activity.id,
                 f"{desc} | {act_date} | "
                 f"{qty} {unit} → {activity.normalized_kg_co2e} kg CO₂e")

            self.out(f"   + Activity [{status:8}]: "
                     f"{act_type:16} {qty:>8} {unit:6} → "
                     f"{activity.normalized_kg_co2e:>10.2f} kg CO₂e"
                     + (" ⚑ flagged" if flag_reasons else ""))

    # ------------------------------------------------------------------ #

    def out(self, msg):
        if not self.quiet:
            self.stdout.write(msg)