import abc
import json
import time

import requests
from django.utils import timezone

from community_base.community.access import ensure_access_grant, reactivate_access, revoke_access
from community_base.community.models import CommunityAuditLog, SlackAccessGrant
from community_base.kernel import conf


class CommunityService(abc.ABC):
    @abc.abstractmethod
    def invite(self, user): ...

    @abc.abstractmethod
    def remove(self, user): ...

    @abc.abstractmethod
    def reactivate(self, user): ...

    @abc.abstractmethod
    def lookup_user_by_email(self, email): ...

    @abc.abstractmethod
    def add_to_channels(self, platform_user_id): ...

    @abc.abstractmethod
    def remove_from_channels(self, platform_user_id): ...


class SlackAPIError(Exception):
    def __init__(self, code, *, method=""):
        self.code = code
        self.method = method
        super().__init__(f"Slack API request failed: {code}")


def _channel_ids():
    raw = conf.get("SLACK_COMMUNITY_CHANNEL_IDS")
    values = raw.split(",") if isinstance(raw, str) else raw
    return tuple(value.strip() for value in values or () if str(value).strip())


class SlackCommunityService(CommunityService):
    def __init__(self, *, token=None, channel_ids=None, request=None, sleep=None):
        self.token = str(token if token is not None else conf.get("SLACK_BOT_TOKEN")).strip()
        self.channel_ids = tuple(channel_ids) if channel_ids is not None else _channel_ids()
        self.request = request or requests.post
        self.sleep = sleep or time.sleep

    def _api_call(self, method, **payload):
        if not conf.get("SLACK_ENABLED") or not self.token:
            raise SlackAPIError("not_configured", method=method)
        url = f"{str(conf.get('SLACK_API_BASE_URL')).rstrip('/')}/{method}"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json; charset=utf-8",
        }
        for attempt in range(2):
            try:
                response = self.request(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=float(conf.get("SLACK_HTTP_TIMEOUT")),
                )
            except requests.RequestException as error:
                raise SlackAPIError("network_error", method=method) from error
            if response.status_code == 429 and attempt == 0:
                raw_delay = response.headers.get("Retry-After", "5")
                delay = int(raw_delay) if str(raw_delay).isdigit() else 5
                self.sleep(min(delay, 30))
                continue
            if response.status_code == 429:
                raise SlackAPIError("ratelimited", method=method)
            if response.status_code >= 500:
                raise SlackAPIError("server_error", method=method)
            try:
                data = response.json()
            except ValueError as error:
                raise SlackAPIError("invalid_response", method=method) from error
            if not data.get("ok"):
                raise SlackAPIError(str(data.get("error") or "unknown_error"), method=method)
            return data
        raise SlackAPIError("ratelimited", method=method)

    def iter_workspace_members(self):
        cursor = ""
        while True:
            data = self._api_call("users.list", limit=200, cursor=cursor)
            yield from data.get("members", ())
            cursor = str((data.get("response_metadata") or {}).get("next_cursor") or "")
            if not cursor:
                return

    def lookup_user_by_email(self, email):
        try:
            return self._api_call("users.lookupByEmail", email=email).get("user", {}).get("id")
        except SlackAPIError as error:
            if error.code == "users_not_found":
                return None
            raise

    def check_workspace_membership(self, email):
        try:
            user_id = self.lookup_user_by_email(email)
        except SlackAPIError:
            return "unknown", None
        return ("member", user_id) if user_id else ("not_member", None)

    def add_to_channels(self, platform_user_id):
        return self._update_channels("conversations.invite", platform_user_id)

    def remove_from_channels(self, platform_user_id):
        return self._update_channels("conversations.kick", platform_user_id)

    def _update_channels(self, method, user_id):
        results = []
        harmless = "already_in_channel" if method.endswith("invite") else "not_in_channel"
        argument = "users" if method.endswith("invite") else "user"
        for channel in self.channel_ids:
            try:
                self._api_call(method, channel=channel, **{argument: user_id})
                results.append({"channel": channel, "ok": True})
            except SlackAPIError as error:
                results.append(
                    {
                        "channel": channel,
                        "ok": error.code == harmless,
                        "error": "" if error.code == harmless else error.code,
                    }
                )
        return results

    def _resolve_user_id(self, user):
        user_id = user.slack_user_id or self.lookup_user_by_email(user.email)
        if user_id and user.slack_user_id != user_id:
            user.slack_user_id = user_id
            user.save(update_fields=("slack_user_id",))
        return user_id

    def invite(self, user):
        grant, _changed, delivery = ensure_access_grant(
            user, source=SlackAccessGrant.Source.ELIGIBILITY
        )
        user_id = self._resolve_user_id(user)
        results = self.add_to_channels(user_id) if user_id else []
        self._audit(user, CommunityAuditLog.Action.INVITE, user_id, results)
        return grant, delivery, results

    def remove(self, user):
        grant, _changed = revoke_access(user)
        results = self.remove_from_channels(user.slack_user_id) if user.slack_user_id else []
        self._audit(user, CommunityAuditLog.Action.REMOVE, user.slack_user_id, results)
        return grant, results

    def reactivate(self, user):
        grant, _changed, delivery = reactivate_access(user)
        user_id = self._resolve_user_id(user)
        results = self.add_to_channels(user_id) if user_id else []
        self._audit(user, CommunityAuditLog.Action.REACTIVATE, user_id, results)
        return grant, delivery, results

    def _audit(self, user, action, user_id, results):
        CommunityAuditLog.objects.create(
            user=user,
            action=action,
            details=json.dumps(
                {
                    "platform_user_id": user_id or "",
                    "channels": results,
                },
                sort_keys=True,
            ),
        )


def sync_membership(user, *, service=None):
    service = service or SlackCommunityService()
    state, user_id = service.check_workspace_membership(user.email)
    if state == "unknown":
        return state
    user.slack_member = state == "member"
    if user_id and not user.slack_user_id:
        user.slack_user_id = user_id
    user.slack_checked_at = timezone.now()
    fields = ["slack_member", "slack_checked_at"]
    if user_id:
        fields.append("slack_user_id")
    user.save(update_fields=fields)
    CommunityAuditLog.objects.create(
        user=user, action=CommunityAuditLog.Action.CHECK, details=f"membership_{state}"
    )
    return state


def get_community_service():
    return SlackCommunityService()
