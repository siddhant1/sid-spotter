from django.urls import path, re_path

from planner import views

urlpatterns = [
    path("api/health", views.health),
    path("api/geocode", views.geocode),
    path("api/plan", views.plan),
    path("api/heatmap", views.heatmap),
    re_path(r"^(?!api/).*$", views.spa),
]
