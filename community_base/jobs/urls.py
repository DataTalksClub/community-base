from django.urls import path

from community_base.jobs.ingress import run_job

app_name = "cb_jobs"

urlpatterns = [
    path("run", run_job, name="run"),
]
