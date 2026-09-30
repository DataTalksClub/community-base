import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("cb_coursework", "0005_authored_homework_metadata"),
        ("cb_curriculum", "0004_module_syllabus_section"),
    ]

    operations = [
        migrations.AddField(
            model_name="project",
            name="commit_id_field",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="project",
            name="module",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="projects",
                to="cb_curriculum.module",
            ),
        ),
        migrations.AlterField(
            model_name="projectsubmission",
            name="commit_id",
            field=models.CharField(blank=True, max_length=40),
        ),
    ]
