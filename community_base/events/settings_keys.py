from community_base.config.registry import declare

declare(
    key="EVENT_URL_STYLE",
    group="events",
    label="Event URL style",
    description="Canonical event route style: slug or public_id.",
    value_type="str",
    default="slug",
)
declare(
    key="EVENT_PRIVACY_NOTICE_VERSION",
    group="events",
    label="Event privacy notice version",
    description="Version recorded when an accountless attendee accepts the privacy notice.",
    value_type="str",
    default="1",
)
declare(
    key="EVENT_NEWSLETTER_CONSENT_VERSION",
    group="events",
    label="Event newsletter consent version",
    description="Version recorded with an accountless attendee newsletter choice.",
    value_type="str",
    default="1",
)
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
declare(
    key="ZOOM_AUTO_RECORDING",
    group="zoom",
    label="Zoom auto recording",
    description="Zoom recording mode: cloud, local or none.",
    value_type="str",
    default="cloud",
)
declare(
    key="ZOOM_JOIN_BEFORE_HOST",
    group="zoom",
    label="Zoom join before host",
    description="Allow participants to join before the host.",
    value_type="bool",
    default=False,
)
declare(
    key="ZOOM_WAITING_ROOM",
    group="zoom",
    label="Zoom waiting room",
    description="Require participants to enter the waiting room.",
    value_type="bool",
    default=False,
)
