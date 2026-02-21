"""View definitions for Route Tracking plugin.

This module defines the UI views for displaying and managing route tracking data.
All views inherit from NautobotUIViewSet provided by Nautobot.

References:
- Nautobot Views: https://docs.nautobot.com/projects/core/en/stable/development/apps/api/views/nautobotuiviewset/
- Nautobot 3.x Tab Views: https://docs.nautobot.com/projects/core/en/stable/development/apps/api/views/

"""

from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views import View
from django_tables2 import RequestConfig
from nautobot.apps.views import NautobotUIViewSet
from nautobot.core.views.mixins import ObjectPermissionRequiredMixin
from nautobot.core.views.paginator import EnhancedPaginator, get_paginate_count
from nautobot.dcim.models import Device

from nautobot_route_tracking.api.serializers import RouteEntrySerializer
from nautobot_route_tracking.filters import RouteEntryFilterSet
from nautobot_route_tracking.forms import RouteEntryFilterForm
from nautobot_route_tracking.models import RouteEntry
from nautobot_route_tracking.tables import RouteEntryDeviceTable, RouteEntryTable


class RouteEntryUIViewSet(NautobotUIViewSet):
    """UI ViewSet for RouteEntry model (read-only).

    Route entries are created exclusively by collection jobs. Manual
    create/edit is disabled — no form_class is set and no add button
    is exposed in the navigation.

    See: https://docs.nautobot.com/projects/core/en/stable/development/apps/api/views/nautobotuiviewset/
    """

    queryset = RouteEntry.objects.select_related(
        "device",
        "device__location",
        "vrf",
        "outgoing_interface",
    ).prefetch_related("tags")
    filterset_class = RouteEntryFilterSet
    filterset_form_class = RouteEntryFilterForm
    table_class = RouteEntryTable
    serializer_class = RouteEntrySerializer

    # Read-only: only export, no add/edit/delete/bulk buttons
    action_buttons = ("export",)

    # Lookup field for detail views
    lookup_field = "pk"


class DeviceRouteTabView(ObjectPermissionRequiredMixin, View):
    """Tab view showing Route Entries for a specific Device.

    Used as a tab on the Device detail page via TemplateExtension.

    See: https://docs.nautobot.com/projects/core/en/stable/development/apps/api/ui-extensions/template-extensions/
    """

    permission_required = "nautobot_route_tracking.view_routeentry"
    queryset = RouteEntry.objects.all()

    template_name = "nautobot_route_tracking/device_route_tab.html"

    def get_required_permission(self):
        """Return the required permission for this view."""
        return self.permission_required

    def get(self, request: HttpRequest, pk: str) -> HttpResponse:
        """Handle GET request for device route tab."""
        device = get_object_or_404(Device.objects.restrict(request.user, "view"), pk=pk)

        # Get route entries for this device, filtered by object-level permissions
        route_entries = (
            RouteEntry.objects.restrict(request.user, "view")
            .filter(device=device)
            .select_related("vrf", "outgoing_interface")
            .order_by("-last_seen")
        )

        # Create table
        table = RouteEntryDeviceTable(route_entries)

        # Configure pagination
        per_page = get_paginate_count(request)
        RequestConfig(
            request,
            paginate={"per_page": per_page, "paginator_class": EnhancedPaginator},
        ).configure(table)

        return render(
            request,
            self.template_name,
            {
                "object": device,
                "table": table,
                "active_tab": "routes",
            },
        )
