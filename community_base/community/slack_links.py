import re

from community_base.kernel import conf

_SLACK_ID = re.compile(r"^[A-Z][A-Z0-9]{1,31}$")


def build_slack_profile_url(slack_user_id, team_id=None):
    """Return a canonical web deep link only for validated Slack IDs."""
    user_id = str(slack_user_id or "").strip()
    workspace_id = str(team_id if team_id is not None else conf.get("SLACK_TEAM_ID")).strip()
    if not _SLACK_ID.fullmatch(user_id) or not _SLACK_ID.fullmatch(workspace_id):
        return ""
    return f"https://app.slack.com/client/{workspace_id}/{user_id}"
