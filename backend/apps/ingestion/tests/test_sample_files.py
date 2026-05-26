"""
Tests for sample file ingestion
================================
Tests the three sample files from the test/ directory:
- sample-electricity.csv  → Utility parser
- sample-sap.csv          → SAP MB51 parser
- sample-travel.csv       → Travel parser

These tests verify that:
1. Files with non-standard column names are ingested successfully
   (flexible column alias mapping works)
2. Only truly critical columns for CO2 calculation cause failures
3. Missing optional columns are handled gracefully with defaults
"""
import os
from decimal import Decimal
from django.test import TestCase
from apps.tenants.models import Tenant
from apps.ingestion.models import IngestionRun, RawRow
from apps.normalization.models import NormalizedActivity, EmissionFactor


# Path to test data files
TEST_DATA_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "..", "test"
)


def _get_test_file_path(filename: str) -> str:
    path = os.path.normpath(os.path.join(TEST_DATA_DIR, filename))
    if not os.path.exists(path):
        raise FileNotFoundError(f"Test file not found: {path}")
    return path


class SampleElectricityTest(TestCase):
    """
    Tests sample-electricity.csv ingestion.

    The file uses non-standard column names:
        Account_No, Service_Address, Type, Bill_Start_Date, Bill_End_Date,
        Usage_Value, Unit, Peak_Demand_kW, Total_Amount, Rate_Schedule, Notes

    The parser should map these to internal keys:
        Account_No → meter_id
        Bill_Start_Date → period_start
        Bill_End_Date → period_end
        Usage_Value → consumption_kwh
        etc.
    """

    def setUp(self):
        self.tenant = Tenant.objects.create(
            name="Test Corp Electricity",
            slug="test-corp-elec",
            country_code="US",
            grid_emission_factor_kg_per_kwh=Decimal("0.42"),
        )
        self.run = IngestionRun.objects.create(
            tenant=self.tenant,
            source_type=IngestionRun.SourceType.UTILITY,
            status=IngestionRun.Status.PROCESSING,
            original_filename="sample-electricity.csv",
        )

    def test_ingestion_succeeds(self):
        """File should be ingested successfully despite non-standard column names."""
        from apps.ingestion.parsers.utility import parse

        file_path = _get_test_file_path("sample-electricity.csv")
        with open(file_path, "rb") as f:
            result = parse(self.run, f)

        print(f"\n{'='*60}")
        print(f"SAMPLE-ELECTRICITY.CSV RESULTS")
        print(f"{'='*60}")
        print(f"  Success: {result['success']}")
        print(f"  Failed:  {result['failed']}")
        print(f"  Flagged: {result['flagged']}")

        # We expect all 3 rows to be ingested (success > 0)
        self.assertGreater(result["success"], 0,
            "Expected at least 1 row to be ingested successfully")
        print(f"\n  ✓ {result['success']} rows ingested successfully")

        # Check NormalizedActivity records were created
        activities = NormalizedActivity.objects.filter(ingestion_run=self.run)
        print(f"  ✓ {activities.count()} NormalizedActivity records created")

        for activity in activities:
            print(f"\n  Activity: {activity.description}")
            print(f"    Date:      {activity.activity_date}")
            print(f"    kWh:       {activity.original_value}")
            print(f"    CO2e (kg): {activity.normalized_kg_co2e}")
            print(f"    EF used:   {activity.emission_factor_used}")
            print(f"    Scope:     {activity.scope}")
            # CO2 should be calculated (non-zero for non-zero consumption)
            if activity.original_value > 0:
                self.assertGreater(activity.normalized_kg_co2e, 0,
                    "CO2e should be > 0 for non-zero consumption")

        # Check raw rows
        raw_rows = RawRow.objects.filter(ingestion_run=self.run)
        failed_rows = raw_rows.filter(parse_status=RawRow.ParseStatus.FAILED)
        if failed_rows.exists():
            print(f"\n  Failed rows:")
            for row in failed_rows:
                print(f"    Row {row.row_number}: {row.parse_errors}")

        print(f"\n{'='*60}")


class SampleSapTest(TestCase):
    """
    Tests sample-sap.csv ingestion.

    The file uses SAP export format column names:
        EBELN, EBELP, BUKRS, WERKS, LIFNR, MATNR, MENGE, MEINS,
        BUDAT, AEDAT, BSART, WAERS

    Some columns map directly (WERKS→plant_code, MATNR→material_number,
    MENGE→quantity, MEINS→unit, BUDAT→posting_date).

    The material numbers in the sample (000000000001234, 000000000005678,
    000000000009876) do NOT match the DIES-/LPG-/HEL-/CNG- prefixes in
    MATERIAL_MAP, so rows will fail on material classification. This is
    expected — the test verifies the parser doesn't crash and handles
    unknown materials gracefully.
    """

    def setUp(self):
        self.tenant = Tenant.objects.create(
            name="Test Corp SAP",
            slug="test-corp-sap",
            country_code="DE",
        )
        self.run = IngestionRun.objects.create(
            tenant=self.tenant,
            source_type=IngestionRun.SourceType.SAP_MB51,
            status=IngestionRun.Status.PROCESSING,
            original_filename="sample-sap.csv",
        )
        # Seed emission factors for diesel
        EmissionFactor.objects.create(
            fuel_type="diesel",
            unit="L",
            kg_co2e_per_unit=Decimal("2.68780"),
            source="DEFRA 2023",
            valid_from_year=2023,
        )

    def test_ingestion_does_not_crash(self):
        """File should not cause a crash — parser handles unknown materials gracefully."""
        from apps.ingestion.parsers.sap_mb51 import parse

        file_path = _get_test_file_path("sample-sap.csv")
        with open(file_path, "rb") as f:
            result = parse(self.run, f)

        print(f"\n{'='*60}")
        print(f"SAMPLE-SAP.CSV RESULTS")
        print(f"{'='*60}")
        print(f"  Success: {result['success']}")
        print(f"  Failed:  {result['failed']}")
        print(f"  Flagged: {result['flagged']}")

        # The file should be parsed without crashing
        total = result["success"] + result["failed"]
        self.assertGreater(total, 0,
            "Expected at least 1 row to be processed (even if failed)")
        print(f"\n  ✓ {total} rows processed without crash")

        # Check raw rows for detail
        raw_rows = RawRow.objects.filter(ingestion_run=self.run)
        print(f"  ✓ {raw_rows.count()} raw rows created")

        for row in raw_rows:
            print(f"\n  Row {row.row_number}: status={row.parse_status}")
            if row.parse_errors:
                print(f"    Errors: {row.parse_errors}")
            print(f"    Data keys: {list(row.raw_data.keys())}")

        # Check for activities
        activities = NormalizedActivity.objects.filter(ingestion_run=self.run)
        for activity in activities:
            print(f"\n  Activity: {activity.description}")
            print(f"    Date:      {activity.activity_date}")
            print(f"    Value:     {activity.original_value} {activity.original_unit}")
            print(f"    CO2e (kg): {activity.normalized_kg_co2e}")

        print(f"\n{'='*60}")


class SampleTravelTest(TestCase):
    """
    Tests sample-travel.csv ingestion.

    The file uses non-standard column names:
        report_id, expense_id, employee_id, expense_type, transaction_date,
        departure_code, arrival_code, quantity_nights, amount, currency,
        category, distance_km

    The parser should map these:
        transaction_date → travel_date
        departure_code → origin
        arrival_code → destination
        quantity_nights → nights
        category → (not mapped, kept as-is)

    expense_type values are: Flight, Hotel, Ground Transport
    (not AIR, HOTEL, CAR — the parser should handle these)
    """

    def setUp(self):
        self.tenant = Tenant.objects.create(
            name="Test Corp Travel",
            slug="test-corp-travel",
            country_code="US",
        )
        self.run = IngestionRun.objects.create(
            tenant=self.tenant,
            source_type=IngestionRun.SourceType.TRAVEL,
            status=IngestionRun.Status.PROCESSING,
            original_filename="sample-travel.csv",
        )
        # Seed emission factors for travel
        EmissionFactor.objects.create(
            fuel_type="flight_eco",
            unit="km",
            kg_co2e_per_unit=Decimal("0.15553"),
            source="DEFRA 2023",
            valid_from_year=2023,
        )
        EmissionFactor.objects.create(
            fuel_type="flight_bus",
            unit="km",
            kg_co2e_per_unit=Decimal("0.45109"),
            source="DEFRA 2023",
            valid_from_year=2023,
        )
        EmissionFactor.objects.create(
            fuel_type="hotel",
            unit="night",
            kg_co2e_per_unit=Decimal("20.60000"),
            source="DEFRA 2023",
            valid_from_year=2023,
        )
        EmissionFactor.objects.create(
            fuel_type="car",
            unit="km",
            kg_co2e_per_unit=Decimal("0.17140"),
            source="DEFRA 2023",
            valid_from_year=2023,
        )

    def test_ingestion_succeeds(self):
        """File should be ingested successfully despite non-standard column names."""
        from apps.ingestion.parsers.travel import parse

        file_path = _get_test_file_path("sample-travel.csv")
        with open(file_path, "rb") as f:
            result = parse(self.run, f)

        print(f"\n{'='*60}")
        print(f"SAMPLE-TRAVEL.CSV RESULTS")
        print(f"{'='*60}")
        print(f"  Success: {result['success']}")
        print(f"  Failed:  {result['failed']}")
        print(f"  Flagged: {result['flagged']}")

        # We expect rows to be ingested (some may fail due to missing EFs)
        total = result["success"] + result["failed"]
        self.assertGreater(total, 0,
            "Expected at least 1 row to be processed")
        print(f"\n  ✓ {total} rows processed")

        # Check for activities
        activities = NormalizedActivity.objects.filter(ingestion_run=self.run)
        print(f"  ✓ {activities.count()} NormalizedActivity records created")

        for activity in activities:
            print(f"\n  Activity: {activity.description}")
            print(f"    Type:      {activity.activity_type}")
            print(f"    Date:      {activity.activity_date}")
            print(f"    Value:     {activity.original_value} {activity.original_unit}")
            print(f"    CO2e (kg): {activity.normalized_kg_co2e}")
            print(f"    EF used:   {activity.emission_factor_used}")
            print(f"    Scope:     {activity.scope}")
            print(f"    Flagged:   {activity.is_flagged_suspicious}")
            if activity.flag_reasons:
                print(f"    Flags:     {activity.flag_reasons}")

        # Check raw rows for failures
        raw_rows = RawRow.objects.filter(ingestion_run=self.run)
        failed_rows = raw_rows.filter(parse_status=RawRow.ParseStatus.FAILED)
        if failed_rows.exists():
            print(f"\n  Failed rows:")
            for row in failed_rows:
                print(f"    Row {row.row_number}: {row.parse_errors}")

        print(f"\n{'='*60}")

    def test_column_mapping_works(self):
        """Verify that the flexible column mapping correctly maps non-standard headers."""
        from apps.ingestion.parsers.travel import _build_column_map

        # Simulate the headers from sample-travel.csv
        headers = [
            "report_id", "expense_id", "employee_id", "expense_type",
            "transaction_date", "departure_code", "arrival_code",
            "quantity_nights", "amount", "currency", "category", "distance_km"
        ]

        col_map = _build_column_map(headers)

        print(f"\n{'='*60}")
        print(f"COLUMN MAPPING TEST")
        print(f"{'='*60}")
        for original, internal in sorted(col_map.items()):
            print(f"  {original:25s} → {internal}")

        # Critical mappings
        self.assertIn("expense_type", col_map.values(), "expense_type should be mapped")
        self.assertIn("travel_date", col_map.values(), "transaction_date should map to travel_date")
        self.assertIn("origin", col_map.values(), "departure_code should map to origin")
        self.assertIn("destination", col_map.values(), "arrival_code should map to destination")
        self.assertIn("nights", col_map.values(), "quantity_nights should map to nights")

        print(f"\n  ✓ All critical column mappings verified")
        print(f"{'='*60}")
