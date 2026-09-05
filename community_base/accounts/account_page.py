from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils.cache import patch_cache_control, patch_vary_headers
from django.views.decorators.http import require_GET

from community_base.accounts.models import ProfessionalRole, Seniority, WorkStatus
from community_base.accounts.services.profile import serialize_profile
from community_base.accounts.services.timezones import build_timezone_options


@login_required
@require_GET
def account_view(request):
    response = render(
        request,
        "accounts/account.html",
        {
            "profile": serialize_profile(request.user),
            "work_status_choices": WorkStatus.choices,
            "professional_role_choices": ProfessionalRole.choices,
            "seniority_choices": Seniority.choices,
            "timezone_options": build_timezone_options(),
        },
    )
    patch_cache_control(response, private=True, no_cache=True, no_store=True, max_age=0)
    patch_vary_headers(response, ("Cookie",))
    return response
