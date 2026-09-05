# Onboarding flows

`community_base.onboarding` composes account profiles, questionnaires, AI interviews and
site-owned steps into resumable member onboarding. It uses the new Django label `cb_onboarding`, so
sites can install it without colliding with an existing app label.

## Installation

Install onboarding after accounts and questionnaires, and add Studio when staff need to configure
flows or review progress.

```python
INSTALLED_APPS = [
    "community_base.kernel",
    "community_base.accounts",
    "community_base.questionnaires",
    "community_base.studio",
    "community_base.onboarding",
]
```

Mount the member and staff routes.

```python
urlpatterns = [
    path("onboarding/", include("community_base.onboarding.urls")),
    path("studio/", include("community_base.studio.urls")),
    path("studio/", include("community_base.onboarding.studio_urls")),
]
```

## Flow selection and progress

Create one active `OnboardingFlow` with `is_default=True`, then add `FlowAssignment` rows when a
group or access level needs a different flow. `flow_for(user)` checks active assignments from highest to
lowest priority. An assignment matches when the member belongs to its group or the configured
`ACCESS_POLICY` grants its `min_level`.

`OnboardingProgress` stores the selected flow, current step, completion time and adapter data. Once
a member starts, assignment changes don't move their incomplete progress to another flow. The
engine resumes that record and skips profile or questionnaire work that the member already
completed.

After the completion transaction commits, the engine sends `onboarding_completed` with `user` and
`flow` keyword arguments. Keep notification, community invite and site analytics work in receivers
rather than importing those domains into this app.

## Step configuration

Order steps with distinct non-negative `order` values inside each flow, and set `required=False`
when members may skip a step.

- `profile` renders and saves the shared `MemberProfile`. A member must complete every required
  profile field and verify their email before continuing.
- `questionnaire` uses `config={"questionnaire_slug": "welcome"}` for one active onboarding
  questionnaire, or `config={"persona_selection": true}` to show the shared persona choices and
  route to the selected questionnaire.
- `ai_chat` redirects to the optional questionnaire AI transport. Keep
  `AI_ONBOARDING_COMPLETE_URL` and `AI_ONBOARDING_FALLBACK_URL` pointed at `/onboarding/` so the flow
  can resume after the interview.
- `plan` calls `COMMUNITY_BASE["ONBOARDING_PLAN_STEP"]` with `request`, `step` and `progress`.
- `custom` renders the site template named by `config={"template": "site/onboarding/example.html"}`.

Use either `questionnaire` or `ai_chat` in one flow. Both adapters produce the same member-owned
onboarding response, so Studio validation rejects a flow that mixes them.

A custom template receives `progress` and `step`, and it completes the step by posting to
`community_base_onboarding_submit`. A plan hook can return an `HttpResponse` directly or a context
dictionary containing `{"complete": true}` on POST when the site-owned plan work finished.

The default plan hook reports that the step is unavailable. A required plan step remains open until
a site configures the hook, while a member can skip an optional plan step.

## Eligibility and member routes

`COMMUNITY_BASE["ONBOARDING_ELIGIBILITY"]` accepts a callable or dotted path that receives the member
and returns a boolean. The default allows authenticated members, while AISL can supply its
paid-access predicate and DTC can require a verified account.

Member routes require login and use private, uncached responses.

- `GET /onboarding/` starts or resumes the selected flow.
- `GET /onboarding/resume/` is a stable resume alias.
- `GET /onboarding/step/` renders the current adapter.
- `POST /onboarding/submit/` saves, advances or skips the current adapter.
- `GET /onboarding/prompt/` renders the dashboard prompt partial when onboarding is available and
  incomplete.

Sites can also include `community_base/onboarding/_dashboard_prompt.html` from their own dashboard
when they already provide the matching context. The prompt links back to the stable start route.

## Studio operations

Mount `community_base.onboarding.studio_urls` under the same prefix as the Studio shell. Staff can
create and edit flows, add or remove steps, manage assignments and search progress records. Studio
validates the JSON object required by each step kind before saving it.

The package doesn't seed flows because questionnaire slugs, site groups, access levels, templates
and plan behavior differ by site. Add each site's initial flow in an idempotent site migration or
management command.
