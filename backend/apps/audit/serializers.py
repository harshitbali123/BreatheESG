from rest_framework import serializers
from .models import AuditLog


class AuditLogSerializer(serializers.ModelSerializer):
	class Meta:
		model = AuditLog
		fields = [
			"id",
			"timestamp",
			"actor",
			"action",
			"target_type",
			"target_id",
			"detail",
		]
