"""Template content extensions for Route Tracking plugin.

This module defines template extensions that add tabs and sidebar panels
to Nautobot's built-in Device detail views.

References:
- Nautobot Template Extensions: https://docs.nautobot.com/projects/core/en/stable/development/apps/api/templates/

"""

from django.urls import reverse
from nautobot.apps.ui import TemplateExtension

from nautobot_route_tracking.models import RouteEntry


class DeviceRouteTab(TemplateExtension):
    """Add Route Tracking tab and panel to Device detail view.

    Adds the following to Device detail:
    - Routes tab: Shows collected routing table entries for this device
    - Right sidebar panel: Shows route count summary

    See: https://docs.nautobot.com/projects/core/en/stable/development/apps/api/templates/
    """

    model = "dcim.device"

    def detail_tabs(self):
        """Return tab definitions for device detail view."""
        return [
            {
                "title": "Routes",
                "url": reverse(
                    "plugins:nautobot_route_tracking:device_route_tab",
                    kwargs={"pk": self.context["object"].pk},
                ),
            },
        ]

    def right_page(self):
        """Add route statistics panel to device detail right sidebar."""
        device = self.context["object"]
        request = self.context["request"]
        qs = RouteEntry.objects.restrict(request.user, "view").filter(device=device)
        route_count = qs.count()

        return self.render(
            "nautobot_route_tracking/inc/device_route_panel.html",
            extra_context={
                "route_count": route_count,
                "object": device,
            },
        )


# Register template extensions
template_extensions = [DeviceRouteTab]
