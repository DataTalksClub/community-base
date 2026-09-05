import json
import uuid
from importlib import import_module

from django.contrib.auth.decorators import login_required
from django.http import Http404, StreamingHttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from community_base.kernel import conf
from community_base.questionnaires import ai_backend
from community_base.questionnaires.onboarding import get_onboarding_response


def _services():
    try:
        return import_module("community_base.questionnaires.services_onboarding_ai")
    except ImportError as error:
        if error.name == "pydantic":
            raise Http404("AI onboarding requires the community-base[ai] extra") from None
        raise


def _destination(name):
    return conf.get(name)


def _require_available():
    if not ai_backend.is_enabled():
        raise Http404("AI onboarding is unavailable")


def _context(conversation, response, **extra):
    transcript = conversation.transcript if isinstance(conversation.transcript, list) else []
    return {
        "conversation": conversation,
        "response": response,
        "chat_messages": transcript,
        "turn_request_id": uuid.uuid4(),
        "draft_message": "",
        **extra,
    }


@login_required
def chat(request):
    _require_available()
    services = _services()
    existing = get_onboarding_response(request.user)
    if existing is not None and existing.status == "submitted":
        return redirect(_destination("AI_ONBOARDING_COMPLETE_URL"))
    response, conversation = services.get_or_create_ai_onboarding_response(request.user)
    if response is None:
        return redirect(_destination("AI_ONBOARDING_FALLBACK_URL"))
    if not conversation.transcript:
        services.run_member_turn(conversation, None)
    return render(request, "questionnaires/ai_chat.html", _context(conversation, response))


def _error_message(code):
    return {
        "busy": "Another reply is still processing. Please wait and retry.",
        "altered_message": "That retry no longer matches the original message.",
        "attempts_exhausted": "That reply could not be retried. Start a new message.",
    }.get(code, "That reply could not be processed. Please try again.")


@login_required
@require_POST
def message(request):
    _require_available()
    services = _services()
    response, conversation = services.get_or_create_ai_onboarding_response(request.user)
    if response is None:
        return redirect(_destination("AI_ONBOARDING_FALLBACK_URL"))
    member_message = request.POST.get("message", "").strip()
    request_id = request.POST.get("request_id", "").strip()
    if not member_message or not request_id:
        return render(
            request,
            "questionnaires/ai_chat.html",
            _context(
                conversation,
                response,
                error="Type a message and retry." if not member_message else "Please retry.",
                draft_message=member_message,
            ),
            status=400,
        )
    try:
        outcome = services.run_logical_member_turn(conversation, request_id, member_message)
    except services.TurnRequestError as error:
        return render(
            request,
            "questionnaires/ai_chat.html",
            _context(
                conversation,
                response,
                error=_error_message(error.code),
                draft_message=member_message,
            ),
            status=409,
        )
    except ai_backend.LLMError:
        return redirect(_destination("AI_ONBOARDING_FALLBACK_URL"))
    response.refresh_from_db(fields=("status",))
    if response.status == "submitted":
        return redirect(_destination("AI_ONBOARDING_COMPLETE_URL"))
    if outcome.replayed:
        conversation.refresh_from_db(fields=("transcript",))
    return render(request, "questionnaires/ai_chat.html", _context(conversation, response))


def _sse(event, payload):
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"


def _stream_response(iterator):
    response = StreamingHttpResponse(iterator, content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


@login_required
@require_POST
def stream(request):
    _require_available()
    services = _services()
    response, conversation = services.get_or_create_ai_onboarding_response(request.user)
    member_message = request.POST.get("message", "").strip()
    request_id = request.POST.get("request_id", "").strip()
    if response is None or not member_message or not request_id:
        return _stream_response(iter((_sse("error", {"reason": "invalid-request"}),)))
    try:
        turns = services.stream_logical_member_turn(conversation, request_id, member_message)
    except services.TurnRequestError as error:
        return _stream_response(iter((_sse("error", {"reason": error.code}),)))

    def events():
        try:
            for item in turns:
                if isinstance(item, str):
                    yield _sse("delta", {"text": item})
                else:
                    response.refresh_from_db(fields=("status",))
                    yield _sse(
                        "done",
                        {
                            "complete": response.status == "submitted",
                            "replayed": item.replayed,
                            "redirect": (
                                _destination("AI_ONBOARDING_COMPLETE_URL")
                                if response.status == "submitted"
                                else None
                            ),
                        },
                    )
        except services.TurnRequestError as error:
            yield _sse("error", {"reason": error.code})
        except ai_backend.LLMError:
            yield _sse("fallback", {"reason": "provider-error"})
        finally:
            close = getattr(turns, "close", None)
            if close is not None:
                close()

    return _stream_response(events())
