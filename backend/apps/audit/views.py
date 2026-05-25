from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from .models import AuditLog
from .serializers import AuditLogSerializer


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
	permission_classes = [IsAuthenticated]
	serializer_class = AuditLogSerializer

	def get_queryset(self):
		return AuditLog.objects.filter(tenant=self.request.user.tenant).order_by("-timestamp")
