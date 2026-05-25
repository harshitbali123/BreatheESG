from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import UploadView, IngestionRunViewSet

router = DefaultRouter()
router.register(r"runs", IngestionRunViewSet, basename="ingestion-run")

urlpatterns = [
    path("upload/", UploadView.as_view(), name="ingestion-upload"),
    path("", include(router.urls)),
]