"""View definitions for Route Tracking plugin.

This module defines the UI views for displaying and managing route tracking data.
All views inherit from NautobotUIViewSet provided by Nautobot.

References:
- Nautobot Views: https://docs.nautobot.com/projects/core/en/stable/development/apps/api/views/nautobotuiviewset/
- Nautobot 3.x Tab Views: https://docs.nautobot.com/projects/core/en/stable/development/apps/api/views/

"""

import json
from datetime import timedelta

from django.db.models import Count
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
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


class RouteDashboardView(ObjectPermissionRequiredMixin, View):
    """Dashboard view with route tracking statistics and charts.

    Provides an overview of all collected routing data including:
    - Stat panels (total routes, devices, last collection, stale routes)
    - Charts (routes by protocol, top devices, routes by location)
    - Recently discovered routes table
    """

    permission_required = "nautobot_route_tracking.view_routeentry"
    queryset = RouteEntry.objects.all()

    def get_required_permission(self):
        """Return the required permission for this view."""
        return self.permission_required

    def get(self, request: HttpRequest) -> HttpResponse:
        """Handle GET request for dashboard."""
        qs = RouteEntry.objects.restrict(request.user, "view")
        now = timezone.now()

        # --- Stat panels ---
        total_routes = qs.count()
        active_routes = qs.filter(is_active=True).count()
        devices_collected = qs.values("device").distinct().count()
        stale_routes = qs.stale(days=90).count()
        last_seen_entry = qs.order_by("-last_seen").values_list("last_seen", flat=True).first()

        # --- Charts data ---
        protocol_data = list(
            qs.values("protocol").annotate(count=Count("id")).order_by("-count")
        )
        top_devices = list(
            qs.values("device__name").annotate(count=Count("id")).order_by("-count")[:10]
        )
        location_data = list(
            qs.values("device__location__name").annotate(count=Count("id")).order_by("-count")[:10]
        )

        # --- Recent routes table (last 24h) ---
        recent_routes_qs = qs.filter(
            first_seen__gte=now - timedelta(hours=24),
        ).select_related("device", "vrf").order_by("-first_seen")
        recent_table = RouteEntryTable(list(recent_routes_qs[:25]))

        context = {
            "total_routes": total_routes,
            "active_routes": active_routes,
            "devices_collected": devices_collected,
            "stale_routes": stale_routes,
            "last_collection": last_seen_entry,
            "protocol_data_json": json.dumps(protocol_data),
            "top_devices_json": json.dumps(top_devices),
            "location_data_json": json.dumps(location_data),
            "recent_table": recent_table,
        }
        return render(request, "nautobot_route_tracking/dashboard.html", context)
