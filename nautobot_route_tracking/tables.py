"""Django-tables2 table definitions for Route Tracking plugin.

This module defines the table classes used for rendering RouteEntry data
in the UI. All tables inherit from BaseTable provided by Nautobot.

References:
- Nautobot Tables: https://docs.nautobot.com/projects/core/en/stable/development/apps/api/tables/
- django-tables2: https://django-tables2.readthedocs.io/

"""

import django_tables2 as tables
from nautobot.apps.tables import BaseTable, ButtonsColumn, ToggleColumn

from nautobot_route_tracking.models import RouteEntry


class RouteEntryTable(BaseTable):
    """Full table for the RouteEntry list view.

    Displays all route tracking columns with select/deselect support and
    per-row action buttons. default_columns shows the most useful subset
    while omitting verbose diagnostic columns by default.

    See: https://docs.nautobot.com/projects/core/en/stable/development/apps/api/tables/

    """

    pk = ToggleColumn()
    device = tables.Column(linkify=True)
    vrf = tables.Column(linkify=True)
    network = tables.Column(
        attrs={"td": {"class": "text-nowrap"}},
    )
    protocol = tables.Column()
    next_hop = tables.Column(
        attrs={"td": {"class": "text-nowrap"}},
    )
    outgoing_interface = tables.Column(linkify=True)
    metric = tables.Column()
    admin_distance = tables.Column(verbose_name="AD")
    is_active = tables.BooleanColumn(verbose_name="Active")
    routing_table = tables.Column(verbose_name="VRF/Table")
    first_seen = tables.DateTimeColumn(
        verbose_name="First Seen",
        format="Y-m-d H:i",
    )
    last_seen = tables.DateTimeColumn(
        verbose_name="Last Seen",
        format="Y-m-d H:i",
    )
    actions = ButtonsColumn(RouteEntry, buttons=("changelog",))

    class Meta(BaseTable.Meta):
        """Table metadata."""

        model = RouteEntry
        fields = (
            "pk",
            "device",
            "vrf",
            "network",
            "protocol",
            "next_hop",
            "outgoing_interface",
            "metric",
            "admin_distance",
            "is_active",
            "routing_table",
            "first_seen",
            "last_seen",
            "actions",
        )
        default_columns = (
            "pk",
            "device",
            "vrf",
            "network",
            "protocol",
            "next_hop",
            "admin_distance",
            "is_active",
            "last_seen",
            "actions",
        )


class RouteEntryDeviceTable(BaseTable):
    """Simplified route table for the Device detail tab.

    Omits the ``device`` column (implied by context) and action buttons.
    No ToggleColumn since no bulk actions are available on this tab.
    default_columns shows the essential subset for a quick per-device overview.

    See: https://docs.nautobot.com/projects/core/en/stable/development/apps/api/tables/

    """

    vrf = tables.Column(linkify=True)
    network = tables.Column(
        attrs={"td": {"class": "text-nowrap"}},
    )
    protocol = tables.Column()
    next_hop = tables.Column(
        attrs={"td": {"class": "text-nowrap"}},
    )
    outgoing_interface = tables.Column(linkify=True)
    metric = tables.Column()
    admin_distance = tables.Column(verbose_name="AD")
    is_active = tables.BooleanColumn(verbose_name="Active")
    routing_table = tables.Column(verbose_name="VRF/Table")
    first_seen = tables.DateTimeColumn(
        verbose_name="First Seen",
        format="Y-m-d H:i",
    )
    last_seen = tables.DateTimeColumn(
        verbose_name="Last Seen",
        format="Y-m-d H:i",
    )

    class Meta(BaseTable.Meta):
        """Table metadata."""

        model = RouteEntry
        fields = (
            "vrf",
            "network",
            "protocol",
            "next_hop",
            "outgoing_interface",
            "metric",
            "admin_distance",
            "is_active",
            "routing_table",
            "first_seen",
            "last_seen",
        )
        default_columns = (
            "network",
            "protocol",
            "next_hop",
            "is_active",
            "last_seen",
        )
