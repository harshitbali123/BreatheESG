from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from .models import Tenant
from .serializers import TenantSerializer


class TenantViewSet(viewsets.ReadOnlyModelViewSet):
	"""Simple read-only viewset for tenants.

	Exposes list and retrieve endpoints for Tenant objects.
	"""
	permission_classes = [IsAuthenticated]
	queryset = Tenant.objects.all().order_by("name")
	serializer_class = TenantSerializer
