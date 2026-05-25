from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from .models import NormalizedActivity, EmissionFactor
from .serializers import NormalizedActivityListSerializer, EmissionFactorSerializer


class NormalizedActivityViewSet(viewsets.ReadOnlyModelViewSet):
	permission_classes = [IsAuthenticated]
	serializer_class = NormalizedActivityListSerializer

	def get_queryset(self):
		return NormalizedActivity.objects.filter(tenant=self.request.user.tenant).select_related("ingestion_run").order_by("-activity_date")


class EmissionFactorViewSet(viewsets.ReadOnlyModelViewSet):
	permission_classes = [IsAuthenticated]
	queryset = EmissionFactor.objects.all().order_by("fuel_type")
	serializer_class = EmissionFactorSerializer
