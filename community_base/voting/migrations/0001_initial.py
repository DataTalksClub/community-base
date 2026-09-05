import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL)]

    operations = [
        migrations.CreateModel(
            name="Poll",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("title", models.CharField(max_length=300)),
                ("description", models.TextField(blank=True, default="")),
                ("poll_type", models.CharField(choices=[("topic", "Topic"), ("course", "Mini-course")], default="topic", max_length=20)),
                ("required_level", models.IntegerField(default=20)),
                ("status", models.CharField(choices=[("open", "Open"), ("closed", "Closed")], default="open", max_length=20)),
                ("allow_proposals", models.BooleanField(default=False)),
                ("max_votes_per_user", models.PositiveIntegerField(default=3)),
                ("closes_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ("-created_at",)},
        ),
        migrations.CreateModel(
            name="PollOption",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("title", models.CharField(max_length=300)),
                ("description", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("poll", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="options", to="voting.poll")),
                ("proposed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="proposed_options", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("created_at",)},
        ),
        migrations.CreateModel(
            name="PollVote",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("option", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="votes", to="voting.polloption")),
                ("poll", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="votes", to="voting.poll")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="poll_votes", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ("-created_at",),
                "constraints": [models.UniqueConstraint(fields=("poll", "user", "option"), name="voting_unique_poll_user_option")],
            },
        ),
    ]
