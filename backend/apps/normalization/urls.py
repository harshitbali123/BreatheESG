from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import NormalizedActivityViewSet, EmissionFactorViewSet

router = DefaultRouter()
router.register(r"activities", NormalizedActivityViewSet, basename="normalized-activity")
router.register(r"emission-factors", EmissionFactorViewSet, basename="emission-factor")

urlpatterns = [
	path("", include(router.urls)),
]
