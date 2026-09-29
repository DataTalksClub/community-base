"""One safe template-key contract for Relay and local file templates."""

import re

TEMPLATE_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
