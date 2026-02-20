"""Form definitions for Route Tracking plugin.

This module defines the form classes used for creating, editing, and filtering
RouteEntry data. Forms inherit from NautobotModelForm and NautobotFilterForm.

References:
- Nautobot Forms: https://docs.nautobot.com/projects/core/en/stable/development/apps/api/forms/

"""

from django import forms
from nautobot.apps.forms import (
    DateTimePicker,
    DynamicModelMultipleChoiceField,
    NautobotFilterForm,
    TagFilterField,
)
from nautobot.dcim.models import Device, Location
from nautobot.extras.models import Role
from nautobot.ipam.models import VRF

from nautobot_route_tracking.models import RouteEntry


class RouteEntryFilterForm(NautobotFilterForm):
    """Filter form for RouteEntry list view.

    Nautobot 3.x compatible with Device Role and Location filters.
    Matches the fields exposed by RouteEntryFilterSet.

    See: https://docs.nautobot.com/projects/core/en/stable/development/apps/api/forms/

    """

    model = RouteEntry

    q = forms.CharField(
        required=False,
        label="Search",
    )
    device = DynamicModelMultipleChoiceField(
        queryset=Device.objects.all(),
        required=False,
        label="Device",
    )
    device_role = DynamicModelMultipleChoiceField(
        queryset=Role.objects.all(),
        required=False,
        label="Device Role",
    )
    location = DynamicModelMultipleChoiceField(
        queryset=Location.objects.all(),
        required=False,
        label="Location",
    )
    vrf = DynamicModelMultipleChoiceField(
        queryset=VRF.objects.all(),
        required=False,
        label="VRF",
    )
    protocol = forms.MultipleChoiceField(
        choices=RouteEntry.Protocol.choices,
        required=False,
        label="Protocol",
    )
    network = forms.CharField(
        required=False,
        label="Network (partial match)",
    )
    next_hop = forms.CharField(
        required=False,
        label="Next Hop (partial match)",
    )
    is_active = forms.NullBooleanField(
        required=False,
        widget=forms.Select(choices=[("", "---------"), ("true", "Yes"), ("false", "No")]),
        label="Is Active",
    )
    routing_table = forms.CharField(
        required=False,
        label="Routing Table (partial match)",
    )
    first_seen_after = forms.DateTimeField(
        required=False,
        widget=DateTimePicker(),
        label="First Seen After",
    )
    first_seen_before = forms.DateTimeField(
        required=False,
        widget=DateTimePicker(),
        label="First Seen Before",
    )
    last_seen_after = forms.DateTimeField(
        required=False,
        widget=DateTimePicker(),
        label="Last Seen After",
    )
    last_seen_before = forms.DateTimeField(
        required=False,
        widget=DateTimePicker(),
        label="Last Seen Before",
    )
    tags = TagFilterField(model)
