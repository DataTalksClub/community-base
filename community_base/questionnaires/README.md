# Questionnaires

`community_base.questionnaires` stores reusable questionnaires, immutable response snapshots and
durable AI onboarding conversations. Install the app when a site needs member questionnaires or
the shared Studio authoring and review pages.

We keep the Django label `questionnaires`, and the initial migration remains provisional. Don't tag
or release a package containing it until AISL schema preparation and the C3.7 compatibility
rehearsal are complete.

## Installation

Install the package app after accounts. Add Studio when staff need to author questionnaires or
review responses.

```python
INSTALLED_APPS = [
    "community_base.kernel",
    "community_base.accounts",
    "community_base.studio",
    "community_base.questionnaires",
]
```

Mount member and staff routes:

```python
from django.urls import include, path

urlpatterns = [
    path("questionnaires/", include("community_base.questionnaires.urls")),
    path("studio/", include("community_base.studio.urls")),
    path("studio/", include("community_base.questionnaires.studio_urls")),
]
```

The member URL group currently contains the optional AI chat transport. C3.3 will compose the
profile, questionnaire, AI chat and plan screens into configurable onboarding flows.

## Responses and snapshots

Call `get_or_create_response(questionnaire, respondent)` before rendering a member form. The
service copies each current `Question` and `QuestionOption` into response-owned snapshot rows.
Later edits or reordering of the source questionnaire can't change a response already in progress.

Render `questionnaires/_response_form.html` with the `response` and its prefetched snapshot rows.
Pass a submitted mapping to `save_response_answers(response, data, submit=True)` to validate and
store answers. The service raises `ResponseValidationError` with field errors when required values,
choice IDs, free text or numeric bounds are invalid. A successful submit sets `submitted_at` and
clears any prior review state.

Questionnaire and persona content is site-owned. Seed each site's questionnaires and persona copy
in a site migration or an idempotent site command. The package doesn't install AISL's named
personas or onboarding copy.

## Studio operations

Staff can author questionnaire metadata, questions, options and personas. JSON endpoints reorder
questions, options and personas atomically after checking that every submitted ID belongs to the
requested collection. Reordering never writes response snapshots.

The response queue supports status, review, purpose and text filters. Staff can open a queue scoped
to one questionnaire, review or reopen submitted responses and add response-specific questions.
Configure `COMMUNITY_BASE["STUDIO_AUDIT_WRITER"]` if a site needs durable review audit records.

## AI onboarding

Install the optional provider dependencies only on sites that enable AI onboarding:

```bash
uv add "community-base[ai]"
```

Configure these keys inside `COMMUNITY_BASE`.

- `AI_ONBOARDING`: enables provider calls when an API key is also present. It defaults to `False`.
- `AI_API_KEY`: supplies the Anthropic API credential. It defaults to `""`.
- `AI_BASE_URL`: selects the Anthropic-compatible API origin. It defaults to
  `"https://api.anthropic.com"`.
- `AI_MODEL`: selects the provider model. It defaults to `"claude-sonnet-4-5"`.
- `AI_MAX_RETRIES`: controls provider client retries. It defaults to `2`.
- `AI_ONBOARDING_DEADLINE_SECONDS`: sets the whole-turn deadline. It defaults to `25`.
- `AI_ONBOARDING_MAX_ATTEMPTS`: limits application-level turn attempts. It defaults to `2`.
- `AI_ONBOARDING_FALLBACK_URL`: redirects after an unavailable AI turn. It defaults to
  `"/onboarding/"`.
- `AI_ONBOARDING_COMPLETE_URL`: redirects after AI completion. It defaults to `"/onboarding/"`.
- `AI_ONBOARDING_COMPLETED_HOOK`: names a callable notified with `attempt_id` after completion. It
  defaults to `None`.

The package imports the Anthropic client only when it makes a configured provider call. Base
installations can import and mount questionnaire routes without `anthropic` or Pydantic.

Each `OnboardingConversation` stores the canonical transcript and a monotonic turn version.
`OnboardingTurnAttempt` provides request idempotency, a single-processing-turn constraint, leases,
retry and provider timing fields. The message and stream endpoints reject stale or competing turns
before a provider call. They return safe failure codes and never persist the API key or raw provider
exceptions.

The completion hook receives `attempt_id` as a keyword argument. A site can use that opaque ID to
queue its own notification, but the package doesn't import a site notification model.

## Adoption assumptions

Follow these boundaries during site adoption.

- Sites keep the `questionnaires` app label and existing table names during adoption.
- C3.7 owns migration replacement metadata and fresh-versus-upgrade schema equivalence.
- C3.3 owns access policy, flow selection and the surrounding onboarding screens.
- Site code owns persona and questionnaire copy, notification delivery and profile or plan steps.
- Sites install the `ai` extra only when they enable AI onboarding.
