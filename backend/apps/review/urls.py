from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import NormalizedActivityViewSet, ReviewSummaryView

router = DefaultRouter()
router.register(r"activities", NormalizedActivityViewSet, basename="review-activity")

urlpatterns = [
	path("", include(router.urls)),
	path("summary/", ReviewSummaryView.as_view(), name="review-summary"),
]
