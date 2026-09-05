from django.urls import path

from community_base.jobs import studio

urlpatterns = [
    path("jobs/", studio.jobs_list, name="community_base_jobs"),
    path("jobs/<uuid:intent_id>/retry/", studio.retry_job, name="community_base_job_retry"),
    path(
        "jobs/<uuid:intent_id>/discard/",
        studio.discard_job,
        name="community_base_job_discard",
    ),
]
