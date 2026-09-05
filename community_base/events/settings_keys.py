from community_base.config.registry import declare

declare(
    key="EVENT_ORGANIZER_EMAIL",
    group="events",
    label="Calendar organizer email",
    description="Mailbox used as the organizer in event calendar invitations.",
    value_type="str",
    default="",
    optional=True,
    is_email=True,
)
declare(
    key="EVENT_ORGANIZER_NAME",
    group="events",
    label="Calendar organizer name",
    description="Display name used for the calendar organizer.",
    value_type="str",
    default="DataTalks.Club",
)
declare(
    key="ZOOM_ENABLED",
    group="zoom",
    label="Zoom enabled",
    description="Allow event jobs to call the configured Zoom account.",
    value_type="bool",
    default=False,
)
declare(
    key="ZOOM_ACCOUNT_ID",
    group="zoom",
    label="Zoom account id",
    description="Server-to-server OAuth account identifier.",
    value_type="str",
    default="",
    secret=True,
    optional=True,
)
declare(
    key="ZOOM_CLIENT_ID",
    group="zoom",
    label="Zoom client id",
    description="Server-to-server OAuth client identifier.",
    value_type="str",
    default="",
    secret=True,
    optional=True,
)
declare(
    key="ZOOM_CLIENT_SECRET",
    group="zoom",
    label="Zoom client secret",
    description="Server-to-server OAuth client secret.",
    value_type="str",
    default="",
    secret=True,
    optional=True,
)
declare(
    key="ZOOM_API_BASE_URL",
    group="zoom",
    label="Zoom API base URL",
    description="Base URL for bounded Zoom API requests.",
    value_type="str",
    default="https://api.zoom.us/v2",
)
declare(
    key="ZOOM_OAUTH_URL",
    group="zoom",
    label="Zoom OAuth URL",
    description="Token endpoint for Zoom server-to-server OAuth.",
    value_type="str",
    default="https://zoom.us/oauth/token",
)
declare(
    key="ZOOM_HTTP_TIMEOUT",
    group="zoom",
    label="Zoom HTTP timeout",
    description="Maximum duration in seconds for each Zoom HTTP request.",
    value_type="int",
    default=10,
)
