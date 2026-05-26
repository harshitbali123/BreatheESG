from rest_framework import viewsets, status
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from django.db import transaction

from .models import Tenant
from .serializers import TenantSerializer, RegisterSerializer


class TenantViewSet(viewsets.ReadOnlyModelViewSet):
	"""Simple read-only viewset for tenants.

	Exposes list and retrieve endpoints for Tenant objects.
	"""
	permission_classes = [IsAuthenticated]
	queryset = Tenant.objects.all().order_by("name")
	serializer_class = TenantSerializer


class RegisterView(APIView):
	"""
	POST /api/tenants/register/

	Public endpoint — no authentication required.
	Creates a new Tenant + Admin User and returns a JWT token pair
	so the user is immediately logged in after registration.
	"""
	permission_classes = [AllowAny]

	def post(self, request):
		serializer = RegisterSerializer(data=request.data)
		if not serializer.is_valid():
			return Response(
				{"detail": "Registration failed.", "errors": serializer.errors},
				status=status.HTTP_400_BAD_REQUEST,
			)

		try:
			with transaction.atomic():
				user = serializer.save()
		except Exception as exc:
			return Response(
				{"detail": f"Registration error: {str(exc)}"},
				status=status.HTTP_500_INTERNAL_SERVER_ERROR,
			)

		# Issue JWT tokens immediately so the user is logged in
		refresh = RefreshToken.for_user(user)
		return Response(
			{
				"detail": "Account created successfully.",
				"username": user.username,
				"organization": user.tenant.name,
				"access": str(refresh.access_token),
				"refresh": str(refresh),
			},
			status=status.HTTP_201_CREATED,
		)
