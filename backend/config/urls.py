from django.contrib import admin
from django.urls import path, include
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

urlpatterns = [
    path("admin/",            admin.site.urls),
    path("api/auth/login/",   TokenObtainPairView.as_view(),  name="token_obtain"),
    path("api/auth/refresh/", TokenRefreshView.as_view(),     name="token_refresh"),
    path("api/ingestion/",    include("apps.ingestion.urls")),
    path("api/normalization/",include("apps.normalization.urls")),
    path("api/review/",       include("apps.review.urls")),
    path("api/audit/",        include("apps.audit.urls")),
    path("api/tenants/",      include("apps.tenants.urls")),
]
