"""API URL configuration for Route Tracking plugin.

This module defines the URL patterns for the plugin's REST API endpoints.

References:
- Nautobot API URLs: https://docs.nautobot.com/projects/core/en/stable/development/apps/api/urls/

"""

from nautobot.apps.api import OrderedDefaultRouter

from nautobot_route_tracking.api.views import RouteEntryViewSet

router = OrderedDefaultRouter()
router.register("route-entries", RouteEntryViewSet)

urlpatterns = router.urls
