from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import TenantViewSet, RegisterView

router = DefaultRouter()
router.register(r"tenants", TenantViewSet, basename="tenant")

urlpatterns = [
	path("", include(router.urls)),
	path("register/", RegisterView.as_view(), name="register"),
]
