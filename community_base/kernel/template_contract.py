"""The public template contract, written down as data so a check can read it.

`docs/02-architecture.md` section 5 states in prose which blocks a shared public page fills
and therefore which slots a consuming site has to expose. Prose cannot be checked, and for as
long as this was only prose neither adopting site exposed all of them and nothing said so:
Django drops the content of an undefined block in silence, so the page renders with the site's
chrome and no body, at HTTP 200, with nothing in the logs.

This module is the same statement as a table. `community_base.kernel.checks` reads it to decide
what to complain about, and `tests/test_template_contract.py` regenerates it from the template
tree and fails if the two disagree, so it cannot drift away from the templates it describes.

Regenerate after adding, removing or reblocking a public template:

    uv run pytest tests/test_template_contract.py -k generated

The failure message prints the rows to paste back into `PUBLIC_TEMPLATES`.
"""

# The package-owned seam every shared public template extends. The default copy shipped in
# `community_base/kernel/templates/` is a pass-through to `SITE_BASE_TEMPLATE`; a site whose
# own chrome names these slots differently overrides this one path instead of editing its base.
PUBLIC_BASE_TEMPLATE = "community_base/public/base.html"

# The consuming site's own base template, which the package never ships and never overrides.
SITE_BASE_TEMPLATE = "base.html"

# How badly a page fails when the site's chain exposes no slot of this name.
#
# `content` is an error: 41 of 41 public templates fill it, and a page whose `content` is
# dropped is a head, a title, the site navigation and no body. Nothing about serving that is
# acceptable, and it is invisible from the outside, so a site is stopped rather than warned.
#
# The other four are warnings. Each loses something real and none of them loses the page: a
# title or description falls back to the site default, `page_head_metadata` loses a `noindex`
# on two mail pages, `extra_js` leaves the static page correct and its progressive enhancement
# dead. A site may also have a coherent answer to one of them under a name of its own, which a
# package error has no standing to call broken. See
# `docs/plan/evidence/c7.25-block-contract-decision-2026-09-18.md`.
BLOCK_SEVERITY: dict[str, str] = {
    "content": "error",
    "title": "warning",
    "meta_description": "warning",
    "page_head_metadata": "warning",
    "extra_js": "warning",
}

CONTRACT_BLOCK_NAMES: tuple[str, ...] = tuple(BLOCK_SEVERITY)

# One check id per block, so a site can silence exactly the one it has answered under a name of
# its own with SILENCED_SYSTEM_CHECKS, instead of silencing the whole contract.
BLOCK_CHECK_ID: dict[str, str] = {
    "content": "community_base.kernel.E001",
    "title": "community_base.kernel.W001",
    "meta_description": "community_base.kernel.W002",
    "page_head_metadata": "community_base.kernel.W003",
    "extra_js": "community_base.kernel.W004",
}

# Raised when the chain under `PUBLIC_BASE_TEMPLATE` cannot be read at all, which is a different
# and louder failure than a missing block: every shared public page raises on render.
UNREADABLE_CHAIN_CHECK_ID = "community_base.kernel.E002"

# Who owns the `main` landmark on a shared public page: the page, not the site's chrome.
#
# All 41 public templates open exactly one `<main class="cb-page">` as the outermost element of
# their `content` block, so a site that does nothing at all still gets one correct landmark per
# page. A site whose chrome opens its own `main` around `content` therefore nests one inside the
# other, which is invalid HTML and leaves assistive technology with two competing landmarks. It
# renders at HTTP 200 and looks right in a browser, which is the class of defect these checks
# exist for, so the chain above the seam is read for it here.
#
# A warning rather than an error, for the same reason the four head blocks are: the page still
# serves its body, the detection is textual and cannot see that a site's `main` sits in a branch
# these pages never take, and a site that knows better silences this one id.
LANDMARK_CHECK_ID = "community_base.kernel.W005"

# The class hook every public `main` carries, so a site has one selector for the page landmark.
PAGE_LANDMARK_CLASS = "cb-page"

# (app import path, template name as the loader sees it, blocks the template fills).
# Generated from the template tree; see the module docstring.
PUBLIC_TEMPLATES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "community_base.accounts",
        "accounts/account.html",
        ("content", "extra_js", "meta_description", "title"),
    ),
    ("community_base.accounts", "accounts/login.html", ("content", "meta_description", "title")),
    (
        "community_base.accounts",
        "accounts/password_reset.html",
        ("content", "meta_description", "title"),
    ),
    (
        "community_base.accounts",
        "accounts/password_reset_complete.html",
        ("content", "meta_description", "title"),
    ),
    (
        "community_base.accounts",
        "accounts/password_reset_request.html",
        ("content", "meta_description", "title"),
    ),
    (
        "community_base.accounts",
        "accounts/password_reset_sent.html",
        ("content", "meta_description", "title"),
    ),
    ("community_base.accounts", "accounts/register.html", ("content", "meta_description", "title")),
    (
        "community_base.accounts",
        "accounts/resend_verification.html",
        ("content", "meta_description", "title"),
    ),
    (
        "community_base.accounts",
        "accounts/verification_result.html",
        ("content", "meta_description", "title"),
    ),
    (
        "community_base.accounts",
        "accounts/verification_sent.html",
        ("content", "meta_description", "title"),
    ),
    ("community_base.community", "community_base/community/call_hosts.html", ("content", "title")),
    (
        "community_base.community",
        "community_base/community/slack_access.html",
        ("content", "title"),
    ),
    ("community_base.coursework", "coursework/certificate.html", ("content", "title")),
    ("community_base.coursework", "coursework/eval.html", ("content", "title")),
    ("community_base.coursework", "coursework/eval_submit.html", ("content", "title")),
    ("community_base.coursework", "coursework/homework.html", ("content", "title")),
    ("community_base.coursework", "coursework/leaderboard.html", ("content", "title")),
    ("community_base.coursework", "coursework/leaderboard_complaint.html", ("content", "title")),
    (
        "community_base.coursework",
        "coursework/leaderboard_score_breakdown.html",
        ("content", "title"),
    ),
    ("community_base.coursework", "coursework/project.html", ("content", "title")),
    (
        "community_base.curriculum",
        "curriculum/course_catalog.html",
        ("content", "meta_description", "title"),
    ),
    (
        "community_base.curriculum",
        "curriculum/course_detail.html",
        ("content", "meta_description", "title"),
    ),
    (
        "community_base.curriculum",
        "curriculum/module_overview.html",
        ("content", "meta_description", "title"),
    ),
    (
        "community_base.curriculum",
        "curriculum/unit_detail.html",
        ("content", "extra_js", "meta_description", "title"),
    ),
    ("community_base.events", "events/event_detail.html", ("content", "meta_description", "title")),
    ("community_base.events", "events/event_list.html", ("content", "meta_description", "title")),
    (
        "community_base.events",
        "events/registration_manage.html",
        ("content", "meta_description", "title"),
    ),
    (
        "community_base.events",
        "events/registration_result.html",
        ("content", "meta_description", "title"),
    ),
    ("community_base.knowledge_base", "knowledge_base/docs_home.html", ("content", "title")),
    (
        "community_base.knowledge_base",
        "knowledge_base/page_detail.html",
        ("content", "meta_description", "title"),
    ),
    ("community_base.knowledge_base", "knowledge_base/wiki_home.html", ("content", "title")),
    (
        "community_base.mail",
        "community_base/mail/click_notice.html",
        ("content", "meta_description", "page_head_metadata", "title"),
    ),
    (
        "community_base.mail",
        "community_base/mail/unsubscribe.html",
        ("content", "meta_description", "page_head_metadata", "title"),
    ),
    ("community_base.notifications", "notifications/notification_list.html", ("content", "title")),
    ("community_base.onboarding", "community_base/onboarding/complete.html", ("content", "title")),
    ("community_base.onboarding", "community_base/onboarding/plan.html", ("content", "title")),
    ("community_base.onboarding", "community_base/onboarding/profile.html", ("content", "title")),
    (
        "community_base.onboarding",
        "community_base/onboarding/questionnaire.html",
        ("content", "title"),
    ),
    ("community_base.questionnaires", "questionnaires/ai_chat.html", ("content",)),
    (
        "community_base.voting",
        "voting/poll_detail.html",
        ("content", "extra_js", "meta_description", "title"),
    ),
    ("community_base.voting", "voting/poll_list.html", ("content", "meta_description", "title")),
)


def templates_for_apps(app_names: set[str]) -> tuple[tuple[str, str, tuple[str, ...]], ...]:
    """The contract rows contributed by the given installed apps."""

    return tuple(row for row in PUBLIC_TEMPLATES if row[0] in app_names)
