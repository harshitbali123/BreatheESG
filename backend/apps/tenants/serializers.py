from rest_framework import serializers
from .models import Tenant


class TenantSerializer(serializers.ModelSerializer):
	class Meta:
		model = Tenant
		fields = [
			"id",
			"name",
			"slug",
			"country_code",
			"timezone",
			"is_active",
			"created_at",
		]
