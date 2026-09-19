"""System checks that keep the public template contract from failing silently.

Every shared public page template in this package extends
``community_base/public/base.html`` and fills some subset of five blocks: ``content``,
``title``, ``meta_description``, ``page_head_metadata`` and ``extra_js``
(``community_base/kernel/template_contract.py`` is that statement as data). The default
copy of ``community_base/public/base.html`` shipped here is a pass-through to the site's
own ``base.html``, and a site whose chrome names those slots differently overrides that one
path to map its names onto the contracted ones.

Django drops the content of a block that no template in the inheritance chain defines. No
exception, no warning, nothing in the logs. So a site whose chain exposes no ``content``
slot serves its full chrome at HTTP 200 with the page body missing, and the page looks
fine. AI-Shipping-Labs/website has been serving its mounted public unsubscribe page that
way -- 21kB of chrome and no form -- and DataTalksClub/website has been dropping the
``noindex, nofollow`` that two mail pages set, both without a single error anywhere
(community-base C7.25, ``docs/plan/evidence/c7.25-block-contract-decision-2026-09-18.md``).

This check compiles the inheritance chain above ``community_base/public/base.html`` and
reads the block names out of it. It does not render anything, and the distinction is
deliberate. ``community_base/studio/checks.py`` answers the narrower Studio version of this
question by rendering probe templates, which is right there because the template it probes
is a package template whose replacement is a package-shaped shell. ``base.html`` is not
that: it is arbitrary site chrome, several hundred lines of it, with the site's own
template tags and context processors, and rendering it with an empty context at
``manage.py check`` time is neither safe nor meaningful. Compiling is still an observation
of the real loader, so a site's override of the seam is seen exactly as Django sees it.

One part of the contract is not a block name. The shared public pages own the `main`
landmark: each opens exactly one `<main class="cb-page">` as the outermost element of its
`content` block, so a site that does nothing gets a correct landmark on every page and a
site's chrome must not open one of its own around `content`. A chain that does nests one
`main` inside another, which is invalid HTML, serves at HTTP 200 and looks right in a
browser -- the same silence the block contract had. That is reported as
`community_base.kernel.W005`, read out of the same chain, as a warning rather than an
error because the page still serves its body and the reading is textual
(community-base C7.30, DataTalksClub/community-base#284).

The two checks sit beside each other and neither subsumes the other. They ask about
different templates on behalf of different page sets: ``community_base.studio.E001`` is
about ``community_base/studio/base.html`` and the Studio shell, this one is about
``community_base/public/base.html`` and the shared public pages.

What this check deliberately does not report, stated so it cannot be read as more assurance
than it is:

- A package template the site has shadowed with its own copy at the same name. Those are
  resolved through the real loader and skipped, because a site's own template fills the
  site's own blocks. This is not hypothetical: AI-Shipping-Labs/website shadows all three
  package knowledge-base templates, and without the skip this check would name four blocks
  there instead of the one that is actually broken.
- Whether a page is mounted. The package cannot know which of its pages a site serves, so
  an unreachable block is reported whether or not the page is reachable. That over-reports
  by construction, which is the safe direction.
- Whether a site's OWN templates honour the site's own base. That is the site's, on the
  surfaces it actually mounts.
"""

import os
import re

from django.apps import apps as django_apps
from django.core.checks import CheckMessage, Error, Tags, Warning, register
from django.template import TemplateDoesNotExist, TemplateSyntaxError
from django.template import engines as template_engines
from django.template.loader_tags import BlockNode, ExtendsNode

from community_base.kernel.template_contract import (
    BLOCK_CHECK_ID,
    BLOCK_SEVERITY,
    LANDMARK_CHECK_ID,
    PUBLIC_BASE_TEMPLATE,
    SITE_BASE_TEMPLATE,
    UNREADABLE_CHAIN_CHECK_ID,
    templates_for_apps,
)

_MAX_CHAIN_DEPTH = 20

_MAIN_RE = re.compile(r"<main\b", re.IGNORECASE)

# Comments are removed before looking for a `main`, so a site that left one commented out in its
# chrome is not accused of opening it.
_COMMENT_RE = re.compile(
    r"<!--.*?-->|\{#.*?#\}|\{%\s*comment\s*.*?%\}.*?\{%\s*endcomment\s*%\}",
    re.DOTALL,
)


def _django_engines() -> list:
    """The DjangoTemplates backends, in the order the loader tries them.

    A Jinja2 or other backend is skipped: block inheritance of this shape is a Django
    template concept, and no package template is written for another engine.
    """

    return [
        backend
        for backend in template_engines.all()
        if hasattr(getattr(backend, "engine", None), "template_loaders")
    ]


def _origin_path(engine, template_name: str) -> str | None:
    """Where this template name resolves on disk, without compiling it.

    Compiling is avoided on purpose: a site's copy of a package template may load template
    libraries this check has no reason to exercise, and a syntax error in one must not turn
    `manage.py check` into a traceback.
    """

    for loader in engine.template_loaders:
        try:
            sources = loader.get_template_sources(template_name)
        except Exception:  # noqa: BLE001 - a custom loader must not break `check`
            continue
        for origin in sources:
            name = getattr(origin, "name", None)
            if name and os.path.exists(name):
                return name
    return None


def _read_chain(engine, template_name: str) -> tuple[set[str], dict[str, str], list[str]]:
    """Read the chain above `template_name`: its block names, its sources, and what broke.

    Returns the set of reachable block names, the source text of every template in the
    chain keyed by name, and a list of human-readable problems. A problem is a template in
    the chain that does not exist, does not compile, or extends a parent named by a
    variable rather than a literal, none of which this check can see past.

    The sources are returned because one part of the contract is not a block name at all:
    the shared public pages bring their own `main`, so a `main` in the chain would nest.
    """

    names: set[str] = set()
    sources: dict[str, str] = {}
    problems: list[str] = []
    seen: set[str] = set()
    pending: list[str] = [template_name]
    while pending and len(seen) < _MAX_CHAIN_DEPTH:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        try:
            template = engine.get_template(name)
        except TemplateDoesNotExist:
            problems.append(f"{name!r} does not exist")
            continue
        except TemplateSyntaxError as error:
            problems.append(f"{name!r} does not compile ({error})")
            continue
        except Exception as error:  # noqa: BLE001 - a broken site template must not break `check`
            problems.append(f"{name!r} could not be read ({error})")
            continue
        nodelist = getattr(template, "nodelist", None)
        if nodelist is None:
            problems.append(f"{name!r} has no readable node list")
            continue
        source = getattr(template, "source", None)
        if isinstance(source, str):
            sources[name] = source
        names.update(node.name for node in nodelist.get_nodes_by_type(BlockNode))
        for extends_node in nodelist.get_nodes_by_type(ExtendsNode):
            parent = getattr(extends_node.parent_name, "var", None)
            if isinstance(parent, str):
                pending.append(parent)
            else:
                problems.append(
                    f"{name!r} extends a parent named by a variable, which cannot be followed"
                )
    return names, sources, problems


def _package_rows(app_configs) -> list[tuple[str, str, tuple[str, ...]]]:
    """Contract rows for the installed package apps, in this project's app registry."""

    configs = app_configs if app_configs is not None else django_apps.get_app_configs()
    installed = {config.name for config in configs}
    return list(templates_for_apps(installed))


@register(Tags.templates)
def check_public_base_block_contract(app_configs, **kwargs) -> list[CheckMessage]:
    """Report every contracted block the site's chain leaves with nowhere to render.

    `content` is an error: the page would serve the site's chrome with no body, at HTTP
    200, and nothing would say so. The other four are warnings: each loses something real
    and none of them loses the page, and a site may have answered one of them under a name
    of its own. See `docs/plan/evidence/c7.25-block-contract-decision-2026-09-18.md`.
    """

    rows = _package_rows(app_configs)
    if not rows:
        return []

    engines = _django_engines()
    if not engines:
        return []

    engine = None
    for backend in engines:
        if _origin_path(backend.engine, PUBLIC_BASE_TEMPLATE):
            engine = backend.engine
            break
    if engine is None:
        engine = engines[0].engine

    reachable, sources, problems = _read_chain(engine, PUBLIC_BASE_TEMPLATE)
    if problems:
        return [
            Error(
                "The template chain above "
                f"{PUBLIC_BASE_TEMPLATE!r} could not be read, so the public block contract "
                "could not be checked and every shared public page may fail to render: "
                + "; ".join(problems)
                + ".",
                hint=(
                    f"{PUBLIC_BASE_TEMPLATE!r} extends {SITE_BASE_TEMPLATE!r}, which the site "
                    "owns. Make sure that template exists, compiles, and names its own parent "
                    "with a literal string. See docs/02-architecture.md section 5."
                ),
                id=UNREADABLE_CHAIN_CHECK_ID,
            )
        ]

    # A package template the site has shadowed is the site's template, filling the site's
    # blocks, and the package has no standing to complain about it.
    package_paths = {config.name: config.path for config in django_apps.get_app_configs()}
    fillers: dict[str, list[str]] = {}
    for app_name, template_name, blocks in rows:
        app_path = package_paths.get(app_name)
        origin = _origin_path(engine, template_name)
        if app_path and origin and not origin.startswith(os.path.join(app_path, "")):
            continue
        for block in blocks:
            fillers.setdefault(block, []).append(template_name)

    messages: list[CheckMessage] = []
    for block in BLOCK_SEVERITY:
        templates = sorted(fillers.get(block, []))
        if not templates or block in reachable:
            continue
        shown = ", ".join(templates[:3])
        if len(templates) > 3:
            shown += f", and {len(templates) - 3} more"
        body = (
            f"No template in the chain above {PUBLIC_BASE_TEMPLATE!r} defines a "
            f"{block!r} block, but {len(templates)} installed package "
            f"{'template fills' if len(templates) == 1 else 'templates fill'} it: {shown}. "
            "Django drops the content of an undefined block with no exception and no log "
            "line, so this is invisible in a rendered page."
        )
        hint = (
            f"Either define {{% block {block} %}} in {SITE_BASE_TEMPLATE!r}, or override "
            f"{PUBLIC_BASE_TEMPLATE!r} in the site's own templates directory and wrap "
            f"{{% block {block} %}} inside whatever this site's base calls that slot. "
            "See docs/02-architecture.md section 5 for a worked example."
        )
        message_class = Error if BLOCK_SEVERITY[block] == "error" else Warning
        messages.append(message_class(body, hint=hint, id=BLOCK_CHECK_ID[block]))

    if fillers:
        messages.extend(_landmark_messages(sources))
    return messages


def _landmark_messages(sources: dict[str, str]) -> list[CheckMessage]:
    """Warn when the site's chrome opens a `main` the shared public pages already opened.

    The landmark is owned by the page, not the chrome: all 41 shared public templates open
    exactly one `<main class="cb-page">` as the outermost element of their `content` block.
    A chain that opens its own `main` around `content` nests one inside the other. That is
    invalid HTML and gives assistive technology two competing landmarks, and like a dropped
    block it is invisible from the outside: the page is HTTP 200 and looks right.
    """

    offenders = sorted(
        name for name, source in sources.items() if _MAIN_RE.search(_COMMENT_RE.sub("", source))
    )
    if not offenders:
        return []
    named = ", ".join(repr(name) for name in offenders)
    return [
        Warning(
            "Every shared public page template opens its own "
            f'<main class="cb-page">, but the template chain above '
            f"{PUBLIC_BASE_TEMPLATE!r} opens a <main> too: {named}. "
            "Those pages render one main inside another, which is invalid HTML and leaves "
            "assistive technology with two competing landmarks. The page still returns 200 and "
            "looks correct in a browser, so nothing else reports it.",
            hint=(
                "Let the page own the landmark: put the site's chrome around "
                f"{{% block content %}} without opening a <main>, and style the "
                "'cb-page' hook instead. A site whose <main> is only on pages these "
                f"templates never reach silences {LANDMARK_CHECK_ID} with "
                "SILENCED_SYSTEM_CHECKS. See docs/02-architecture.md section 5."
            ),
            id=LANDMARK_CHECK_ID,
        )
    ]
