from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.ingestion.models import IngestionRun, RawRow
from apps.tenants.models import Tenant, User


class IngestionRunApiTests(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(
            name="Demo Client",
            slug="demo-client",
            country_code="GB",
        )
        self.other_tenant = Tenant.objects.create(
            name="Other Client",
            slug="other-client",
            country_code="DE",
        )

        self.user = User.objects.create_user(
            username="analyst",
            email="analyst@example.com",
            password="testpass123",
            tenant=self.tenant,
        )
        self.other_user = User.objects.create_user(
            username="other-analyst",
            email="other@example.com",
            password="testpass123",
            tenant=self.other_tenant,
        )

        self.run_newer = IngestionRun.objects.create(
            tenant=self.tenant,
            source_type=IngestionRun.SourceType.TRAVEL,
            status=IngestionRun.Status.COMPLETED,
            original_filename="travel-mar.csv",
            file_hash_sha256="a" * 64,
            uploaded_by=self.user,
            reporting_year=2024,
            row_count_total=3,
            row_count_success=2,
            row_count_failed=1,
            row_count_flagged=1,
        )
        self.run_older = IngestionRun.objects.create(
            tenant=self.tenant,
            source_type=IngestionRun.SourceType.UTILITY,
            status=IngestionRun.Status.FAILED,
            original_filename="utility-feb.csv",
            file_hash_sha256="b" * 64,
            uploaded_by=self.user,
            reporting_year=2024,
            row_count_total=1,
            row_count_success=0,
            row_count_failed=1,
            row_count_flagged=0,
        )
        self.other_run = IngestionRun.objects.create(
            tenant=self.other_tenant,
            source_type=IngestionRun.SourceType.SAP_MB51,
            status=IngestionRun.Status.COMPLETED,
            original_filename="sap.txt",
            file_hash_sha256="c" * 64,
            uploaded_by=self.other_user,
            reporting_year=2024,
            row_count_total=1,
            row_count_success=1,
            row_count_failed=0,
            row_count_flagged=0,
        )

        RawRow.objects.create(
            tenant=self.tenant,
            ingestion_run=self.run_newer,
            row_number=2,
            raw_data={"expense_type": "HOTEL"},
            parse_status=RawRow.ParseStatus.WARNING,
            parse_errors=["missing_nights"],
        )
        RawRow.objects.create(
            tenant=self.tenant,
            ingestion_run=self.run_newer,
            row_number=1,
            raw_data={"expense_type": "AIR"},
            parse_status=RawRow.ParseStatus.OK,
            parse_errors=[],
        )

    def test_list_returns_only_current_tenant_runs_ordered_by_created_at_desc(self):
        self.client.force_authenticate(self.user)
        url = reverse("ingestion-run-list")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 2)
        self.assertEqual(len(response.data["results"]), 2)
        self.assertEqual(response.data["results"][0]["id"], str(self.run_older.id))
        self.assertEqual(response.data["results"][1]["id"], str(self.run_newer.id))
        self.assertEqual(response.data["results"][0]["row_count_failed"], 1)
        self.assertEqual(response.data["results"][0]["status"], IngestionRun.Status.FAILED)
        self.assertNotIn(
            str(self.other_run.id),
            {row["id"] for row in response.data["results"]},
        )

    def test_detail_returns_nested_raw_rows_for_current_tenant_only(self):
        self.client.force_authenticate(self.user)
        url = reverse("ingestion-run-detail", args=[self.run_newer.id])

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], str(self.run_newer.id))
        self.assertEqual(response.data["row_count_total"], 3)
        self.assertEqual(len(response.data["raw_rows"]), 2)
        self.assertEqual(response.data["raw_rows"][0]["row_number"], 1)
        self.assertEqual(response.data["raw_rows"][1]["row_number"], 2)

    def test_detail_is_tenant_scoped(self):
        self.client.force_authenticate(self.user)
        url = reverse("ingestion-run-detail", args=[self.other_run.id])

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
