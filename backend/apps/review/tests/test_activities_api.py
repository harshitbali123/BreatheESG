from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.audit.models import AuditLog
from apps.ingestion.models import IngestionRun, RawRow
from apps.normalization.models import NormalizedActivity
from apps.tenants.models import Tenant, User


class NormalizedActivityApiTests(APITestCase):
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

        self.run_travel = IngestionRun.objects.create(
            tenant=self.tenant,
            source_type=IngestionRun.SourceType.TRAVEL,
            status=IngestionRun.Status.COMPLETED,
            original_filename="travel.csv",
            file_hash_sha256="a" * 64,
            uploaded_by=self.user,
            reporting_year=2024,
            row_count_total=2,
            row_count_success=2,
            row_count_failed=0,
            row_count_flagged=1,
        )
        self.run_utility = IngestionRun.objects.create(
            tenant=self.tenant,
            source_type=IngestionRun.SourceType.UTILITY,
            status=IngestionRun.Status.COMPLETED,
            original_filename="utility.csv",
            file_hash_sha256="b" * 64,
            uploaded_by=self.user,
            reporting_year=2024,
            row_count_total=1,
            row_count_success=1,
            row_count_failed=0,
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

        self.flagged_activity = self._create_activity(
            run=self.run_travel,
            row_number=1,
            activity_date="2024-01-15",
            review_status=NormalizedActivity.ReviewStatus.PENDING,
            activity_type=NormalizedActivity.ActivityType.FLIGHT,
            source_type=self.run_travel.source_type,
            flagged=True,
            scope=NormalizedActivity.Scope.SCOPE_3,
            scope3_category=6,
            description="Flight FRA->LHR",
        )
        self.approved_activity = self._create_activity(
            run=self.run_utility,
            row_number=1,
            activity_date="2024-01-16",
            review_status=NormalizedActivity.ReviewStatus.APPROVED,
            activity_type=NormalizedActivity.ActivityType.ELECTRICITY,
            source_type=self.run_utility.source_type,
            flagged=False,
            scope=NormalizedActivity.Scope.SCOPE_2,
            scope3_category=None,
            description="Electricity bill",
        )
        self.other_activity = self._create_activity(
            run=self.other_run,
            row_number=1,
            activity_date="2024-01-17",
            review_status=NormalizedActivity.ReviewStatus.PENDING,
            activity_type=NormalizedActivity.ActivityType.OTHER,
            source_type=self.other_run.source_type,
            flagged=False,
            scope=NormalizedActivity.Scope.SCOPE_3,
            scope3_category=6,
            description="Other tenant activity",
        )

    def _create_activity(
        self,
        *,
        run,
        row_number,
        activity_date,
        review_status,
        activity_type,
        source_type,
        flagged,
        scope,
        scope3_category,
        description,
    ):
        raw_row = RawRow.objects.create(
            tenant=run.tenant,
            ingestion_run=run,
            row_number=row_number,
            raw_data={"source_type": source_type},
            parse_status=RawRow.ParseStatus.WARNING if flagged else RawRow.ParseStatus.OK,
            parse_errors=["flagged"] if flagged else [],
        )
        return NormalizedActivity.objects.create(
            tenant=run.tenant,
            ingestion_run=run,
            raw_row=raw_row,
            activity_type=activity_type,
            activity_date=activity_date,
            description=description,
            facility_code="",
            facility_name="",
            country_code="",
            cost_center="CC-1",
            vendor="Vendor",
            scope=scope,
            scope3_category=scope3_category,
            original_value=1,
            original_unit="km",
            original_currency="EUR",
            original_amount=100,
            normalized_kg_co2e=12.345678,
            emission_factor_used=0.12345678,
            emission_factor_source="test",
            review_status=review_status,
            is_flagged_suspicious=flagged,
            flag_reasons=["flagged"] if flagged else [],
        )

    def test_list_filters_by_tenant_and_query_params(self):
        self.client.force_authenticate(self.user)
        url = reverse("review-activity-list")

        response = self.client.get(
            url,
            {
                "scope": "3",
                "review_status": "pending",
                "source_type": IngestionRun.SourceType.TRAVEL,
                "flagged": "true",
                "run_id": str(self.run_travel.id),
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(len(response.data["results"]), 1)
        row = response.data["results"][0]
        self.assertEqual(row["id"], str(self.flagged_activity.id))
        self.assertEqual(row["ingestion_run_id"], str(self.run_travel.id))
        self.assertEqual(row["source_type"], IngestionRun.SourceType.TRAVEL)
        self.assertEqual(row["review_status"], NormalizedActivity.ReviewStatus.PENDING)
        self.assertTrue(row["is_flagged_suspicious"])

    def test_list_does_not_leak_other_tenant_data(self):
        self.client.force_authenticate(self.user)
        url = reverse("review-activity-list")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        returned_ids = {row["id"] for row in response.data["results"]}
        self.assertIn(str(self.flagged_activity.id), returned_ids)
        self.assertIn(str(self.approved_activity.id), returned_ids)
        self.assertNotIn(str(self.other_activity.id), returned_ids)

    def test_approve_flag_and_lock_create_audit_logs(self):
        self.client.force_authenticate(self.user)

        approve_url = reverse("review-activity-approve", args=[self.flagged_activity.id])
        response = self.client.post(approve_url, {"note": "looks good"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["review_status"], NormalizedActivity.ReviewStatus.APPROVED)

        self.flagged_activity.refresh_from_db()
        self.assertEqual(self.flagged_activity.review_status, NormalizedActivity.ReviewStatus.APPROVED)

        flag_url = reverse("review-activity-flag", args=[self.approved_activity.id])
        response = self.client.post(flag_url, {"note": "needs review"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["review_status"], NormalizedActivity.ReviewStatus.FLAGGED)
        self.approved_activity.refresh_from_db()
        self.assertEqual(self.approved_activity.review_status, NormalizedActivity.ReviewStatus.FLAGGED)

        lock_url = reverse("review-activity-lock", args=[self.approved_activity.id])
        response = self.client.post(lock_url, {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.approved_activity.refresh_from_db()
        self.assertEqual(self.approved_activity.review_status, NormalizedActivity.ReviewStatus.LOCKED)

        self.assertEqual(
            AuditLog.objects.filter(tenant=self.tenant, target_type="normalized_activity").count(),
            3,
        )

    def test_bulk_approve_updates_multiple_activities(self):
        extra_activity = self._create_activity(
            run=self.run_travel,
            row_number=2,
            activity_date="2024-01-18",
            review_status=NormalizedActivity.ReviewStatus.PENDING,
            activity_type=NormalizedActivity.ActivityType.HOTEL,
            source_type=self.run_travel.source_type,
            flagged=False,
            scope=NormalizedActivity.Scope.SCOPE_3,
            scope3_category=6,
            description="Hotel stay",
        )

        self.client.force_authenticate(self.user)
        url = reverse("review-activity-bulk-approve")

        response = self.client.post(
            url,
            {"ids": [str(self.flagged_activity.id), str(extra_activity.id)]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["updated"], 2)
        self.assertEqual(len(response.data["results"]), 2)
        self.assertEqual(
            AuditLog.objects.filter(
                tenant=self.tenant,
                action=AuditLog.Action.BULK_APPROVED,
                target_type="normalized_activity",
            ).count(),
            2,
        )

    def test_summary_returns_scope_status_and_source_counts(self):
        self.client.force_authenticate(self.user)
        url = reverse("review-summary")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["kg_co2e_by_scope"]["2"], "12.345678")
        self.assertEqual(response.data["kg_co2e_by_scope"]["3"], "12.345678")
        self.assertEqual(response.data["review_status_counts"]["pending"], 1)
        self.assertEqual(response.data["review_status_counts"]["approved"], 1)
        self.assertEqual(response.data["review_status_counts"]["flagged"], 0)
        self.assertEqual(response.data["review_status_counts"]["locked"], 0)
        self.assertEqual(response.data["source_type_counts"]["travel"], 1)
        self.assertEqual(response.data["source_type_counts"]["utility"], 1)
        self.assertEqual(response.data["source_type_counts"]["sap_mb51"], 0)
