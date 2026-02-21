"""Data models for Route Tracking plugin.

This module defines the RouteEntry model for tracking routing table entries
collected from network devices via NAPALM CLI commands.

Key Principle (NetDB Logic):
- UPDATE last_seen if (device, vrf, network, next_hop, protocol) combination exists
- INSERT new record if combination is new or next_hop changes (ECMP = separate rows)

References:
- Nautobot Models: https://docs.nautobot.com/projects/core/en/stable/development/core/models/
- PrimaryModel: https://docs.nautobot.com/projects/core/en/stable/development/apps/api/models/
- NAPALM CLI: https://napalm.readthedocs.io/en/latest/base.html#napalm.base.base.NetworkDriver.cli

"""

import ipaddress

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone
from nautobot.apps.models import PrimaryModel
from nautobot.dcim.models import Device, Interface

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EXCLUDED_ROUTE_NETWORKS: tuple[str, ...] = (
    "224.0.0.0/4",  # IPv4 Multicast (includes 239.0.0.0/8)
    "169.254.0.0/16",  # IPv4 Link-local
    "127.0.0.0/8",  # IPv4 Loopback
    "ff00::/8",  # IPv6 Multicast
    "fe80::/10",  # IPv6 Link-local
    "::1/128",  # IPv6 Loopback
)

# Pre-computed network objects for efficient filtering
_EXCLUDED_NETWORKS = [ipaddress.ip_network(n, strict=False) for n in EXCLUDED_ROUTE_NETWORKS]

SUPPORTED_PLATFORMS: tuple[str, ...] = ("cisco_ios", "arista_eos")


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def is_excluded_route(network: str) -> bool:
    """Check whether a route prefix should be excluded from collection.

    Args:
        network: CIDR prefix string, e.g. "169.254.0.0/16"

    Returns:
        True if the prefix should be excluded, False otherwise.

    """
    try:
        net = ipaddress.ip_network(network, strict=False)
    except ValueError:
        return False

    return any(
        net.version == excluded.version and (net.subnet_of(excluded) or net == excluded)
        for excluded in _EXCLUDED_NETWORKS
    )


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


class RouteEntry(PrimaryModel):
    """Routing table entry collected from a network device.

    This model implements the NetDB UPDATE vs INSERT logic for routing tables:
    - When (device, vrf, network, next_hop, protocol) is unchanged: UPDATE last_seen
    - When a route changes (different next_hop, new protocol): INSERT a new record
    - ECMP routes result in separate rows (one per next_hop)

    Attributes:
        device: The device from which the route was collected
        vrf: The VRF for this route (None = global routing table)
        network: The route prefix in CIDR notation, e.g. "10.0.0.0/8"
        prefix_length: Numeric prefix length (8 for /8) — for efficient range filtering
        protocol: Routing protocol in lowercase, e.g. "ospf", "bgp", "static"
        next_hop: Next-hop IP address (empty string for CONNECTED/LOCAL routes)
        outgoing_interface: Outgoing interface (optional, for CONNECTED routes)
        metric: Route metric / cost
        admin_distance: Administrative distance (preference in NAPALM output)
        is_active: Whether the route is currently installed in the FIB
        routing_table: Raw routing table name from device (e.g. "default", "inet.0")
        first_seen: Timestamp when this route combination was first detected
        last_seen: Timestamp of the most recent detection (updated on each scan)

    """

    class Protocol(models.TextChoices):
        """Routing protocol choices (normalized to lowercase)."""

        OSPF = "ospf", "OSPF"
        BGP = "bgp", "BGP"
        STATIC = "static", "Static"
        CONNECTED = "connected", "Connected"
        ISIS = "isis", "IS-IS"
        RIP = "rip", "RIP"
        EIGRP = "eigrp", "EIGRP"
        LOCAL = "local", "Local"
        UNKNOWN = "unknown", "Unknown"

    device = models.ForeignKey(
        to=Device,
        on_delete=models.CASCADE,
        related_name="route_entries",
        help_text="Device from which the route was collected",
    )
    vrf = models.ForeignKey(
        to="ipam.VRF",
        on_delete=models.SET_NULL,
        related_name="route_entries",
        null=True,
        blank=True,
        help_text="VRF for this route (null = global routing table)",
    )
    network = models.CharField(
        max_length=50,
        help_text="Route prefix in CIDR notation, e.g. '10.0.0.0/8'",
    )
    prefix_length = models.PositiveSmallIntegerField(
        help_text="Numeric prefix length (e.g. 8 for /8) — for efficient range queries",
    )
    protocol = models.CharField(
        max_length=20,
        choices=Protocol.choices,
        help_text="Routing protocol (normalized to lowercase)",
    )
    next_hop = models.CharField(
        max_length=50,
        blank=True,
        default="",
        help_text="Next-hop IP address (empty for CONNECTED/LOCAL routes)",
    )
    outgoing_interface = models.ForeignKey(
        to=Interface,
        on_delete=models.SET_NULL,
        related_name="route_entries",
        null=True,
        blank=True,
        help_text="Outgoing interface (optional, mainly for CONNECTED/LOCAL routes)",
    )
    metric = models.PositiveIntegerField(
        default=0,
        help_text="Route metric or cost",
    )
    admin_distance = models.PositiveSmallIntegerField(
        default=0,
        help_text="Administrative distance (NAPALM 'preference' field)",
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Whether the route is currently installed in the FIB (current_active)",
    )
    routing_table = models.CharField(
        max_length=100,
        default="default",
        help_text="Raw routing table name from device (e.g. 'default', 'inet.0' on JunOS)",
    )
    first_seen = models.DateTimeField(
        auto_now_add=True,
        help_text="When this route combination was first detected",
    )
    last_seen = models.DateTimeField(
        help_text="When this route was last seen (updated on each scan)",
    )

    natural_key_field_lookups = ["device__name", "vrf__name", "network", "protocol", "next_hop"]

    class Meta:
        """Model metadata."""

        verbose_name = "Route Entry"
        verbose_name_plural = "Route Entries"
        ordering = ["-last_seen"]
        constraints = [
            models.UniqueConstraint(
                fields=["device", "vrf", "network", "next_hop", "protocol"],
                name="nautobot_route_tracking_routeentry_unique_route",
            ),
            # PostgreSQL treats NULL as distinct in UNIQUE constraints, so
            # vrf=NULL rows are not protected by the constraint above.
            # This partial index covers the global routing table case.
            models.UniqueConstraint(
                fields=["device", "network", "next_hop", "protocol"],
                condition=models.Q(vrf__isnull=True),
                name="nautobot_route_tracking_routeentry_unique_route_no_vrf",
            ),
        ]
        indexes = [
            models.Index(fields=["device", "last_seen"], name="idx_route_device_lastseen"),
            models.Index(fields=["network", "last_seen"], name="idx_route_network_lastseen"),
            models.Index(fields=["protocol", "last_seen"], name="idx_route_protocol_lastseen"),
            models.Index(fields=["last_seen"], name="idx_route_lastseen"),
            models.Index(fields=["first_seen"], name="idx_route_firstseen"),
        ]

    def __str__(self) -> str:
        """Return string representation."""
        vrf_str = f" [{self.vrf.name}]" if self.vrf else ""
        via_str = f" via {self.next_hop}" if self.next_hop else ""
        return f"{self.device.name}: {self.network}{via_str} ({self.protocol}){vrf_str}"

    def clean_fields(self, exclude=None) -> None:
        """Normalize fields before Django's choices validation.

        Protocol must be lowercased before clean_fields() validates it against
        TextChoices, because NAPALM/EOS returns uppercase protocol names.
        """
        if self.protocol:
            self.protocol = self.protocol.lower()
        super().clean_fields(exclude=exclude)

    def clean(self) -> None:
        """Validate model data.

        Raises:
            ValidationError: If validation fails.

        """
        super().clean()

        # Validate and parse network field
        if self.network:
            try:
                net = ipaddress.ip_network(self.network, strict=False)
                # Normalize to canonical form
                self.network = str(net)
                self.prefix_length = net.prefixlen
            except ValueError as exc:
                raise ValidationError({"network": f"Invalid CIDR prefix: {self.network}"}) from exc

        # Validate outgoing_interface belongs to device
        if self.outgoing_interface and self.device:
            if self.outgoing_interface.device_id != self.device_id:
                raise ValidationError({"outgoing_interface": "Outgoing interface must belong to the specified device"})

        # Set last_seen if not provided
        if not self.last_seen:
            self.last_seen = timezone.now()

    @classmethod
    def update_or_create_entry(
        cls,
        device: Device,
        network: str,
        protocol: str,
        vrf=None,
        next_hop: str = "",
        outgoing_interface: Interface | None = None,
        metric: int = 0,
        admin_distance: int = 0,
        is_active: bool = True,
        routing_table: str = "default",
    ) -> tuple["RouteEntry", bool]:
        """Update existing entry or create new one (NetDB logic).

        This method implements the core NetDB UPDATE vs INSERT logic:
        - If (device, vrf, network, next_hop, protocol) exists: UPDATE last_seen + mutable fields
        - If combination is new: INSERT new record

        ECMP routes (same prefix, different next_hop) produce separate rows.

        Args:
            device: Device where route was collected
            network: Route prefix in CIDR notation (e.g. "10.0.0.0/8")
            protocol: Routing protocol — will be normalized to lowercase
            vrf: Optional VRF FK (None = global routing table)
            next_hop: Next-hop IP address (empty for CONNECTED/LOCAL)
            outgoing_interface: Optional outgoing interface FK
            metric: Route metric
            admin_distance: Administrative distance
            is_active: Whether route is in the FIB
            routing_table: Raw routing table name from device

        Returns:
            Tuple of (RouteEntry instance, created boolean).

        """
        # Normalize protocol
        normalized_protocol = protocol.lower() if protocol else "unknown"

        # Normalize network — raise on invalid CIDR to prevent storing corrupt data
        try:
            net = ipaddress.ip_network(network, strict=False)
            normalized_network = str(net)
            prefix_length = net.prefixlen
        except ValueError as exc:
            raise ValueError(f"Invalid CIDR prefix: {network!r}") from exc

        with transaction.atomic():
            existing = (
                cls.objects.select_for_update()
                .filter(
                    device=device,
                    vrf=vrf,
                    network=normalized_network,
                    next_hop=next_hop,
                    protocol=normalized_protocol,
                )
                .first()
            )

            if existing:
                # UPDATE: same identity, refresh mutable fields
                existing.last_seen = timezone.now()
                existing.metric = metric
                existing.admin_distance = admin_distance
                existing.is_active = is_active
                existing.prefix_length = prefix_length
                existing.routing_table = routing_table
                existing.outgoing_interface = outgoing_interface
                existing.validated_save()
                return existing, False

            # INSERT: new route combination
            entry = cls(
                device=device,
                vrf=vrf,
                network=normalized_network,
                prefix_length=prefix_length,
                protocol=normalized_protocol,
                next_hop=next_hop,
                outgoing_interface=outgoing_interface,
                metric=metric,
                admin_distance=admin_distance,
                is_active=is_active,
                routing_table=routing_table,
                last_seen=timezone.now(),
            )
            entry.validated_save()
            return entry, True
