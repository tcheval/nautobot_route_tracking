"""Django admin registration for Route Tracking plugin.

This module registers the RouteEntry model with the Django admin site,
providing a basic admin interface for direct data inspection and management.

References:
- Django Admin: https://docs.djangoproject.com/en/4.2/ref/contrib/admin/

"""

from django.contrib import admin

from nautobot_route_tracking.models import RouteEntry


@admin.register(RouteEntry)
class RouteEntryAdmin(admin.ModelAdmin):
    """Admin configuration for the RouteEntry model."""

    list_display = ["device", "vrf", "network", "protocol", "next_hop", "is_active", "last_seen"]
    list_filter = ["protocol", "is_active", "device"]
    search_fields = ["network", "next_hop", "device__name"]
    readonly_fields = ["first_seen", "last_seen"]
    list_select_related = ["device", "vrf", "outgoing_interface"]
    raw_id_fields = ["device", "vrf", "outgoing_interface"]
