from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("cb_coursework", "0004_optional_self_paced_due_dates")]

    operations = [
        migrations.AddField(
            model_name="question",
            name="authored_position",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="question",
            name="step_label",
            field=models.CharField(blank=True, default="", max_length=200),
        ),
        migrations.AddField(
            model_name="homework",
            name="stepper_enabled",
            field=models.BooleanField(default=False),
        ),
    ]
