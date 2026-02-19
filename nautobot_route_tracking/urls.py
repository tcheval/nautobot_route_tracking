"""URL configuration for Route Tracking plugin.

This module defines the URL patterns for the plugin's UI views.

References:
- Nautobot URL patterns: https://docs.nautobot.com/projects/core/en/stable/development/apps/api/urls/
- Nautobot 3.x Tab Views: https://docs.nautobot.com/projects/core/en/stable/development/apps/api/ui-extensions/template-extensions/

"""

from django.urls import path
from nautobot.apps.urls import NautobotUIViewSetRouter

from nautobot_route_tracking.views import (
    DeviceRouteTabView,
    RouteEntryUIViewSet,
)

app_name = "nautobot_route_tracking"

router = NautobotUIViewSetRouter()
router.register("route-entries", RouteEntryUIViewSet)

urlpatterns = [
    # Device tab view (used by TemplateExtension)
    path("devices/<uuid:pk>/routes/", DeviceRouteTabView.as_view(), name="device_route_tab"),
]

urlpatterns += router.urls
