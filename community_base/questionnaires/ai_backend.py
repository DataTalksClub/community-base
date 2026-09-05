import logging
import threading
from dataclasses import dataclass

from community_base.kernel import conf

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """Safe provider-neutral AI failure."""


class LLMTimeoutError(LLMError):
    """Provider request exceeded its deadline."""


class CancellationToken:
    def __init__(self):
        self._cancelled = threading.Event()
        self._callbacks = []

    @property
    def cancelled(self):
        return self._cancelled.is_set()

    def register(self, callback):
        if self.cancelled:
            callback()
        else:
            self._callbacks.append(callback)

    def cancel(self):
        if self.cancelled:
            return
        self._cancelled.set()
        for callback in reversed(self._callbacks):
            try:
                callback()
            except Exception:  # noqa: BLE001
                logger.exception("AI provider cleanup failed")
        self._callbacks.clear()


@dataclass
class LLMResult:
    text: str = ""
    tool_input: dict | None = None
    tool_name: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None


@dataclass
class StreamEvent:
    kind: str
    text: str = ""
    result: LLMResult | None = None

    @property
    def is_done(self):
        return self.kind == "done"


def is_enabled():
    return bool(conf.get("AI_ONBOARDING") and str(conf.get("AI_API_KEY")).strip())


def _safe_error(error, key):
    message = f"{type(error).__name__}: {error}"
    return message.replace(key, "***") if key else message


def _parse_response(response):
    text = []
    tool_input = None
    tool_name = None
    for block in getattr(response, "content", None) or ():
        if getattr(block, "type", None) == "text":
            text.append(getattr(block, "text", "") or "")
        elif getattr(block, "type", None) == "tool_use" and tool_input is None:
            tool_input = getattr(block, "input", None)
            tool_name = getattr(block, "name", None)
    rendered = "".join(text).strip()
    if not rendered and tool_input is None:
        raise LLMError("AI provider returned an empty or blocked response")
    usage = getattr(response, "usage", None)
    return LLMResult(
        text=rendered,
        tool_input=tool_input,
        tool_name=tool_name,
        input_tokens=getattr(usage, "input_tokens", None),
        output_tokens=getattr(usage, "output_tokens", None),
        cache_read_tokens=getattr(usage, "cache_read_input_tokens", None),
        cache_write_tokens=getattr(usage, "cache_creation_input_tokens", None),
    )


def _client(*, timeout_seconds=None, max_retries=None, cancellation=None):
    if not is_enabled():
        raise LLMError("AI onboarding is not configured")
    try:
        from anthropic import Anthropic  # noqa: PLC0415
    except ImportError:
        raise LLMError("AI onboarding requires the community-base[ai] extra") from None
    key = str(conf.get("AI_API_KEY")).strip()
    kwargs = {
        "api_key": key,
        "base_url": str(conf.get("AI_BASE_URL")).strip() or None,
        "max_retries": conf.get("AI_MAX_RETRIES") if max_retries is None else max_retries,
    }
    if timeout_seconds is not None:
        kwargs["timeout"] = float(timeout_seconds)
    client = Anthropic(**kwargs)
    if cancellation is not None:
        cancellation.register(client.close)
    return client, key


def complete(
    messages,
    *,
    model=None,
    system=None,
    max_tokens=4096,
    temperature=None,
    tools=None,
    tool_choice=None,
    timeout_seconds=None,
    max_retries=None,
    cancellation=None,
):
    client, key = _client(
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        cancellation=cancellation,
    )
    kwargs = {
        "model": model or conf.get("AI_MODEL"),
        "max_tokens": max_tokens,
        "messages": messages,
    }
    for name, value in (
        ("system", system),
        ("temperature", temperature),
        ("tools", tools),
        ("tool_choice", tool_choice),
    ):
        if value is not None:
            kwargs[name] = value
    try:
        return _parse_response(client.messages.create(**kwargs))
    except LLMError:
        raise
    except Exception as error:
        raise LLMError(f"AI request failed: {_safe_error(error, key)}") from None


def stream(messages, **kwargs):
    client, key = _client(
        timeout_seconds=kwargs.pop("timeout_seconds", None),
        max_retries=kwargs.pop("max_retries", None),
        cancellation=kwargs.pop("cancellation", None),
    )
    request = {
        "model": kwargs.pop("model", None) or conf.get("AI_MODEL"),
        "max_tokens": kwargs.pop("max_tokens", 4096),
        "messages": messages,
        **{name: value for name, value in kwargs.items() if value is not None},
    }
    try:
        with client.messages.stream(**request) as result_stream:
            for text in result_stream.text_stream:
                yield StreamEvent(kind="text_delta", text=text)
            yield StreamEvent(
                kind="done", result=_parse_response(result_stream.get_final_message())
            )
    except LLMError:
        raise
    except Exception as error:
        raise LLMError(f"AI stream failed: {_safe_error(error, key)}") from None
