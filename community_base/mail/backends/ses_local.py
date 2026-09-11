from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

import frontmatter
import markdown
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.template import Context, Template
from django.template.loader import render_to_string
from markdown.extensions import Extension
from markdown.treeprocessors import Treeprocessor

from community_base.config import get as get_config
from community_base.jobs.runner import PermanentJobError, RetryableJobError
from community_base.kernel.conf import get
from community_base.kernel.hooks import resolve
from community_base.mail.models import EmailDelivery

TEMPLATE_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
INLINE_BULLET_PATTERN = re.compile(r"^(?P<lead>.*?:) - (?P<rest>.+)$")


@dataclass(frozen=True, slots=True)
class RenderedEmail:
    subject: str
    body_html: str
    html: str
    plain_text: str
    unsubscribe_url: str | None
    verify_email_url: str | None


@dataclass(frozen=True, slots=True)
class SESResult:
    message_id: str


class ExternalLinksTreeprocessor(Treeprocessor):
    def __init__(self, md, *, site_url: str):
        super().__init__(md)
        self.site_hosts = _site_hosts(site_url)

    def run(self, root):
        for element in root.iter("a"):
            href = (element.get("href") or "").strip()
            parsed = urlparse(href)
            if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
                continue
            if parsed.netloc.lower() in self.site_hosts:
                continue
            if not element.get("target"):
                element.set("target", "_blank")
            tokens = (element.get("rel") or "").split()
            if "noopener" not in {token.casefold() for token in tokens}:
                tokens.append("noopener")
            element.set("rel", " ".join(tokens))


class ExternalLinksExtension(Extension):
    def __init__(self, *, site_url: str):
        self.site_url = site_url
        super().__init__()

    def extendMarkdown(self, md):
        md.treeprocessors.register(
            ExternalLinksTreeprocessor(md, site_url=self.site_url),
            "external_links",
            0,
        )


def deliver(delivery: EmailDelivery, context: Mapping) -> None:
    rendered = render_delivery(delivery, context)
    if delivery.state == EmailDelivery.State.PROVIDER_ACCEPTED and delivery.external_message_id:
        _record(delivery, rendered, SESResult(delivery.external_message_id))
        return

    try:
        result = _send(delivery, rendered)
    except Exception as error:
        _raise_transport_error(delivery, error)

    with transaction.atomic():
        EmailDelivery.objects.filter(pk=delivery.pk).update(
            state=EmailDelivery.State.PROVIDER_ACCEPTED,
            reason_code="",
            external_message_id=result.message_id,
        )
    delivery.state = EmailDelivery.State.PROVIDER_ACCEPTED
    delivery.reason_code = ""
    delivery.external_message_id = result.message_id
    _record(delivery, rendered, result)


def render_delivery(delivery: EmailDelivery, context: Mapping) -> RenderedEmail:
    subject_source, body_source, footer_note = _load_template_source(delivery.template_key)
    site_url = str(context.get("site_url") or get("SITE_URL")).rstrip("/")
    site_name = str(context.get("site_name") or get("STUDIO_TITLE")).removesuffix(" Studio")
    full_context = {
        "user_name": _display_name(delivery),
        "user_email": delivery.recipient_email,
        "site_url": site_url,
        "site_name": site_name,
        **context,
    }
    subject = Template(subject_source).render(Context(full_context))
    body_markdown = Template(body_source).render(Context(full_context))
    body_html = markdown.markdown(
        _normalize_inline_bullets(body_markdown),
        extensions=[
            ExternalLinksExtension(site_url=site_url),
            "fenced_code",
            "tables",
            "attr_list",
            "md_in_html",
        ],
    )
    unsubscribe_url = _unsubscribe_url(delivery)
    verify_email_url = _optional_url("MAIL_VERIFY_EMAIL_URL_BUILDER", delivery)
    html = render_to_string(
        "community_base/mail/email.html",
        {
            "subject": subject,
            "body_html": body_html,
            "site_name": site_name,
            "unsubscribe_url": unsubscribe_url,
            "verify_email_url": verify_email_url,
            "footer_note": footer_note,
        },
    )
    return RenderedEmail(
        subject=subject,
        body_html=body_html,
        html=html,
        plain_text=_plain_text(
            body_markdown,
            site_name=site_name,
            footer_note=footer_note,
            unsubscribe_url=unsubscribe_url,
            verify_email_url=verify_email_url,
        ),
        unsubscribe_url=unsubscribe_url,
        verify_email_url=verify_email_url,
    )


_BLOCK_TAGS = frozenset(
    {
        "blockquote",
        "br",
        "div",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "hr",
        "li",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "tbody",
        "td",
        "th",
        "thead",
        "tr",
        "ul",
    }
)


class _PlainTextHTMLParser(HTMLParser):
    """Flatten rendered email HTML to readable text, keeping link targets."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.chunks: list[str] = []
        self._href: str | None = None
        self._link_text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._link_text = []
        elif tag in _BLOCK_TAGS:
            self.chunks.append("\n")

    def handle_endtag(self, tag):
        if tag == "a":
            text = "".join(self._link_text).strip()
            if self._href and text:
                self.chunks.append(f"{text} ({self._href})")
            else:
                self.chunks.append(text or (self._href or ""))
            self._href = None
            self._link_text = []
        elif tag in _BLOCK_TAGS:
            self.chunks.append("\n")

    def handle_data(self, data):
        target = self._link_text if self._href is not None else self.chunks
        target.append(data)


def _html_to_text(html_source: str) -> str:
    parser = _PlainTextHTMLParser()
    parser.feed(html_source)
    text = "".join(parser.chunks)
    lines = [line.strip() for line in text.splitlines()]
    compacted: list[str] = []
    for line in lines:
        if line or (compacted and compacted[-1]):
            compacted.append(line)
    return "\n".join(compacted).strip()


def _plain_text(
    body_markdown: str,
    *,
    site_name: str,
    footer_note: str,
    unsubscribe_url: str | None,
    verify_email_url: str | None,
) -> str:
    """Derive the SES text part from the same rendered body as the HTML part.

    Mirrors the transitional site renderer's section order: body, site name,
    footer note, verification CTA, unsubscribe action.
    """

    sections = [_html_to_text(markdown.markdown(body_markdown)), site_name]
    if footer_note:
        sections.append(str(footer_note).strip())
    if verify_email_url:
        sections.append(
            f"Your email is not verified on our platform.\nVerify your email: {verify_email_url}"
        )
    if unsubscribe_url:
        sections.append(f"Unsubscribe from all emails: {unsubscribe_url}")
    return "\n\n".join(section for section in sections if section).strip()


def _load_template_source(template_key: str) -> tuple[str, str, str]:
    if not TEMPLATE_KEY_PATTERN.fullmatch(template_key):
        raise PermanentJobError("invalid_mail_template_key")
    loader = _hook("MAIL_TEMPLATE_OVERRIDE_LOADER")
    override = loader(template_key) if loader else None
    if override is not None:
        if not isinstance(override, (tuple, list)) or len(override) not in {2, 3}:
            raise PermanentJobError("invalid_mail_template_override")
        footer_note = str(override[2]) if len(override) == 3 else ""
        return str(override[0]), str(override[1]), footer_note

    root = get("MAIL_TEMPLATE_DIR")
    if not root:
        raise ImproperlyConfigured("COMMUNITY_BASE['MAIL_TEMPLATE_DIR'] is required for ses_local")
    path = Path(root) / f"{template_key}.md"
    if not path.is_file():
        raise PermanentJobError("mail_template_not_found")
    post = frontmatter.load(path)
    return (
        str(post.metadata.get("subject", template_key)),
        post.content,
        str(post.metadata.get("footer_note", "")),
    )


def _send(delivery: EmailDelivery, rendered: RenderedEmail) -> SESResult:
    sender = delivery.sender_id or get_config("SES_FROM_EMAIL")
    if not sender:
        raise ImproperlyConfigured("SES_FROM_EMAIL or a delivery sender is required for ses_local")
    destination = {"ToAddresses": [delivery.recipient_email]}
    for option, key in (("cc", "CcAddresses"), ("bcc", "BccAddresses")):
        addresses = delivery.transport_options.get(option)
        if addresses:
            destination[key] = list(addresses)
    body = {"Html": {"Data": rendered.html, "Charset": "UTF-8"}}
    if rendered.plain_text:
        body["Text"] = {"Data": rendered.plain_text, "Charset": "UTF-8"}
    content = {
        "Simple": {
            "Subject": {"Data": rendered.subject, "Charset": "UTF-8"},
            "Body": body,
        }
    }
    if rendered.unsubscribe_url:
        content["Simple"]["Headers"] = [
            {"Name": "List-Unsubscribe", "Value": f"<{rendered.unsubscribe_url}>"},
            {"Name": "List-Unsubscribe-Post", "Value": "List-Unsubscribe=One-Click"},
        ]
    send_kwargs = {
        "FromEmailAddress": sender,
        "Destination": destination,
        "Content": content,
    }
    reply_to = delivery.transport_options.get("reply_to")
    if reply_to:
        send_kwargs["ReplyToAddresses"] = list(reply_to)
    configuration_set = delivery.transport_options.get("configuration_set")
    if configuration_set:
        send_kwargs["ConfigurationSetName"] = configuration_set
    response = configured_client().send_email(**send_kwargs)
    message_id = response.get("MessageId") if isinstance(response, Mapping) else None
    if not isinstance(message_id, str) or not message_id or len(message_id) > 128:
        raise PermanentJobError("ses_malformed_response")
    return SESResult(message_id)


def configured_client():
    try:
        import boto3
    except ImportError as error:
        raise ImproperlyConfigured(
            "ses_local requires the community-base[ses_local] optional dependency"
        ) from error
    return boto3.client(
        "sesv2",
        region_name=get_config("AWS_SES_REGION"),
        aws_access_key_id=get_config("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=get_config("AWS_SECRET_ACCESS_KEY"),
    )


def _raise_transport_error(delivery: EmailDelivery, error: Exception) -> None:
    if isinstance(error, PermanentJobError):
        _update_failure(delivery, EmailDelivery.State.DEAD, error.code)
        raise error
    if isinstance(error, ImproperlyConfigured):
        _update_failure(delivery, EmailDelivery.State.DEAD, "ses_configuration_error")
        raise PermanentJobError("ses_configuration_error") from error
    try:
        from botocore.exceptions import (
            BotoCoreError,
            ClientError,
            ConnectionClosedError,
            ConnectTimeoutError,
            EndpointConnectionError,
            NoCredentialsError,
            PartialCredentialsError,
            ReadTimeoutError,
        )
    except ImportError:
        BotoCoreError = ClientError = ()
        ConnectionClosedError = ConnectTimeoutError = EndpointConnectionError = ()
        NoCredentialsError = PartialCredentialsError = ReadTimeoutError = ()
    if isinstance(error, (NoCredentialsError, PartialCredentialsError)):
        _update_failure(delivery, EmailDelivery.State.DEAD, "ses_configuration_error")
        raise PermanentJobError("ses_configuration_error") from error
    if isinstance(error, (ReadTimeoutError, ConnectionClosedError)):
        _update_failure(delivery, EmailDelivery.State.AMBIGUOUS, "ses_ambiguous")
        raise PermanentJobError("ses_delivery_ambiguous") from error
    if isinstance(error, (ConnectTimeoutError, EndpointConnectionError)):
        _update_failure(delivery, EmailDelivery.State.RETRYABLE, "ses_unavailable")
        raise RetryableJobError("ses_unavailable") from error
    if isinstance(error, ClientError):
        code = str(error.response.get("Error", {}).get("Code", ""))
        retryable_codes = {
            "TooManyRequestsException",
            "ThrottlingException",
            "ServiceUnavailableException",
        }
        if code in retryable_codes:
            _update_failure(delivery, EmailDelivery.State.RETRYABLE, "ses_unavailable")
            raise RetryableJobError("ses_unavailable") from error
    if isinstance(error, BotoCoreError):
        _update_failure(delivery, EmailDelivery.State.AMBIGUOUS, "ses_ambiguous")
        raise PermanentJobError("ses_delivery_ambiguous") from error
    _update_failure(delivery, EmailDelivery.State.DEAD, "ses_rejected")
    raise PermanentJobError("ses_rejected") from error


def _update_failure(delivery: EmailDelivery, state: str, reason: str) -> None:
    EmailDelivery.objects.filter(pk=delivery.pk).update(state=state, reason_code=reason)


def _record(delivery: EmailDelivery, rendered: RenderedEmail, result: SESResult) -> None:
    recorder = _hook("MAIL_SEND_RECORDER")
    if recorder:
        recorder(delivery, rendered, result)


def _unsubscribe_url(delivery: EmailDelivery) -> str | None:
    return _optional_url("MAIL_UNSUBSCRIBE_URL_BUILDER", delivery)


def _optional_url(hook_name: str, delivery: EmailDelivery) -> str | None:
    builder = _hook(hook_name)
    if not builder:
        return None
    value = builder(delivery)
    if value is None:
        return None
    if not isinstance(value, str) or urlparse(value).scheme not in {"http", "https"}:
        raise PermanentJobError("invalid_mail_action_url")
    return value


def _hook(name: str):
    value = get(name)
    return resolve(value) if isinstance(value, str) else value


def _display_name(delivery: EmailDelivery) -> str:
    user = delivery.recipient_user
    if user is None:
        return ""
    get_full_name = getattr(user, "get_full_name", None)
    if callable(get_full_name) and (name := get_full_name().strip()):
        return name
    return str(getattr(user, "first_name", "") or "")


def _site_hosts(site_url: str) -> set[str]:
    host = urlparse(site_url).netloc.lower()
    if not host:
        return set()
    sibling = host[4:] if host.startswith("www.") else f"www.{host}"
    return {host, sibling}


def _normalize_inline_bullets(text: str) -> str:
    if not text or " - " not in text:
        return text
    output = []
    for line in text.split("\n"):
        match = INLINE_BULLET_PATTERN.match(line)
        if match:
            items = [item.strip() for item in match.group("rest").split(" - ")]
            if len(items) >= 2 and all(items):
                if output and output[-1].strip():
                    output.append("")
                output.extend([match.group("lead"), "", *(f"- {item}" for item in items), ""])
                continue
        output.append(line)
    return "\n".join(output)
