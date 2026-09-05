from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from community_base.accounts.models import ProfessionalRole, Seniority, WorkStatus
from community_base.accounts.services.profile import serialize_profile
from community_base.accounts.services.timezones import build_timezone_options


@login_required
def account_view(request):
    return render(
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
