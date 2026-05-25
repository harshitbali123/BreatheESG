from rest_framework import serializers
from .models import NormalizedActivity, EmissionFactor


class NormalizedActivityListSerializer(serializers.ModelSerializer):
	class Meta:
		model = NormalizedActivity
		fields = [
			"id",
			"activity_type",
			"activity_date",
			"description",
			"facility_code",
			"scope",
			"normalized_kg_co2e",
			"review_status",
		]


class EmissionFactorSerializer(serializers.ModelSerializer):
	class Meta:
		model = EmissionFactor
		fields = "__all__"
