"""Building blocks of the shared project submission form (C5.2n).

Help texts, the commit id format, the repeated learning-in-public link field, and the site-wide
certificate name default. ``project_forms.ProjectSubmissionForm`` assembles them.
"""

import re

from django import forms

from community_base.coursework.projects import clean_learning_in_public_links
from community_base.kernel.conf import get

COMMIT_ID_PATTERN = re.compile(r"^[0-9a-fA-F]{7,40}$")
CLOSED_MESSAGE = "The submission form is closed."

GITHUB_LINK_HELP = "Your project should be hosted on GitHub. Make sure your project is public."
COMMIT_ID_HELP = "Paste the first 7 characters of the commit ID."
LEARNING_IN_PUBLIC_HELP = (
    "Links to social media posts where you share your progress (LinkedIn, X, etc)."
)
TIME_SPENT_HELP = "How much time (in hours) did you spend to work on the project?"
CERTIFICATE_NAME_HELP = "Enter the name you would like to be shown on the certificate."


class LearningInPublicLinksWidget(forms.Widget):
    """Reads every ``<name>`` value of a repeated URL input; renders nothing itself.

    The partial draws the inputs (one per saved link plus one blank slot, and ``+ Add link``
    adds more up to the cap), so the widget only has to collect them.
    """

    def value_from_datadict(self, data, files, name):
        if hasattr(data, "getlist"):
            return data.getlist(name)
        value = data.get(name)
        if value is None:
            return []
        return list(value) if isinstance(value, list | tuple) else [value]

    def value_omitted_from_data(self, data, files, name):
        return False

    def render(self, name, value, attrs=None, renderer=None):
        return ""


class LearningInPublicLinksField(forms.Field):
    """Strip, de-duplicate, cap and validate links with the package's one definition."""

    widget = LearningInPublicLinksWidget

    def __init__(self, *, cap: int, **kwargs):
        self.cap = cap
        kwargs.setdefault("required", False)
        super().__init__(**kwargs)

    def to_python(self, value):
        if not value:
            return []
        if isinstance(value, str):
            value = [value]
        return [str(link) for link in value]

    def clean(self, value):
        links = self.to_python(value)
        return clean_learning_in_public_links(links, self.cap)


def certificate_name_field_enabled() -> bool:
    """The site-wide default for the certificate name field (``True`` keeps CMP parity)."""

    return bool(get("COURSEWORK_PROJECT_CERTIFICATE_NAME_FIELD"))
