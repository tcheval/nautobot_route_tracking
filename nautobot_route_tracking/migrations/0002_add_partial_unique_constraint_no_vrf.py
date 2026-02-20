# Generated manually for partial unique constraint on vrf IS NULL

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("nautobot_route_tracking", "0001_initial"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="routeentry",
            constraint=models.UniqueConstraint(
                condition=models.Q(vrf__isnull=True),
                fields=["device", "network", "next_hop", "protocol"],
                name="nautobot_route_tracking_routeentry_unique_route_no_vrf",
            ),
        ),
    ]
