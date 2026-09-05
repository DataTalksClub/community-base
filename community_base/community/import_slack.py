from community_base.accounts.models import IMPORT_SOURCE_SLACK
from community_base.accounts.services.import_users import ImportRow, register_import_adapter
from community_base.community.services import SlackCommunityService


def _skip(member):
    return bool(
        member.get("deleted")
        or member.get("is_bot")
        or member.get("is_app_user")
        or member.get("name") == "slackbot"
        or member.get("is_primary_owner")
    )


def slack_import_rows(_payload=None, *, service=None):
    service = service or SlackCommunityService()
    for member in service.iter_workspace_members():
        if _skip(member):
            continue
        profile = member.get("profile") or {}
        email = str(profile.get("email") or "").strip()
        if not email:
            yield {"email": "", "metadata": {"slack_id": member.get("id", "")}}
            continue
        name = str(profile.get("real_name_normalized") or member.get("real_name") or "").strip()
        parts = name.split(maxsplit=1)
        tags = ["slack-member"]
        if member.get("is_admin"):
            tags.append("slack-admin")
        if member.get("is_ultra_restricted"):
            tags.append("slack-guest")
        yield ImportRow(
            email=email,
            first_name=parts[0] if parts else "",
            last_name=parts[1] if len(parts) == 2 else "",
            email_verified=True,
            account_activated=True,
            tags=tuple(tags),
            metadata={
                "slack_id": member.get("id", ""),
                "slack_team_id": member.get("team_id", ""),
            },
            fields={
                "slack_user_id": member.get("id", ""),
                "slack_member": True,
                "preferred_timezone": member.get("tz", ""),
            },
        )


def register_slack_import_adapter():
    register_import_adapter(IMPORT_SOURCE_SLACK, slack_import_rows)
