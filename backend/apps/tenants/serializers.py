from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from .models import Tenant, User


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


class RegisterSerializer(serializers.Serializer):
	"""
	Handles new user registration.
	Creates a Tenant and a User in one atomic operation.
	"""
	# User fields
	username      = serializers.CharField(max_length=150)
	email         = serializers.EmailField(required=False, allow_blank=True)
	password      = serializers.CharField(write_only=True)
	confirm_password = serializers.CharField(write_only=True)
	first_name    = serializers.CharField(max_length=150, required=False, allow_blank=True)
	last_name     = serializers.CharField(max_length=150, required=False, allow_blank=True)

	# Tenant fields
	organization_name = serializers.CharField(max_length=255)
	country_code      = serializers.CharField(max_length=2, default='US')

	def validate_username(self, value):
		if User.objects.filter(username=value).exists():
			raise serializers.ValidationError('A user with this username already exists.')
		return value

	def validate_email(self, value):
		if value and User.objects.filter(email=value).exists():
			raise serializers.ValidationError('A user with this email already exists.')
		return value

	def validate(self, data):
		if data['password'] != data['confirm_password']:
			raise serializers.ValidationError({'confirm_password': 'Passwords do not match.'})
		validate_password(data['password'])
		return data

	def create(self, validated_data):
		import re
		org_name = validated_data['organization_name']
		# Generate a unique slug from org name
		base_slug = re.sub(r'[^a-z0-9]+', '-', org_name.lower()).strip('-')[:90]
		slug = base_slug
		counter = 1
		while Tenant.objects.filter(slug=slug).exists():
			slug = f'{base_slug}-{counter}'
			counter += 1

		tenant = Tenant.objects.create(
			name=org_name,
			slug=slug,
			country_code=validated_data.get('country_code', 'US'),
		)

		user = User.objects.create_user(
			username=validated_data['username'],
			email=validated_data.get('email', ''),
			password=validated_data['password'],
			first_name=validated_data.get('first_name', ''),
			last_name=validated_data.get('last_name', ''),
			tenant=tenant,
			role=User.Role.ADMIN,  # first user of org is admin
		)
		return user
