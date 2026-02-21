"""Shared constants for Route Tracking plugin."""

# Platforms with a supported napalm_cli parser for route collection.
# Maps to Platform.network_driver values in Nautobot.
SUPPORTED_PLATFORMS: tuple[str, ...] = ("cisco_ios", "arista_eos")
