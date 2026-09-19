from __future__ import annotations

import json
from typing import Any, Dict, Tuple

import requests

from urllib.parse import urlencode

from .config import (
    CHATGPT_REALTIME_CALLS_URL,
    CHATGPT_REALTIME_LIVE_URL,
    CHATGPT_REALTIME_WS_URL,
    LIVE_ARCHITECTURE,
    LIVE_INTENT,
    QUICKSILVER_ALPHA,
)
from .upstream import build_upstream_headers
from .utils import get_effective_chatgpt_auth

# Model names the Codex client carries for voice. The backend decides what it
# actually runs, so this is a request and not a guarantee -- same deal as the
# image model.
DEFAULT_REALTIME_MODEL = "gpt-realtime-1.5"
REALTIME_MODELS = (DEFAULT_REALTIME_MODEL, "gpt-live-1-codex")

SDP_CONTENT_TYPE = "application/sdp"


class RealtimeRequestError(Exception):
    def __init__(self, message: str, *, status_code: int = 400, code: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def extract_offer(raw_body: str, content_type: str | None) -> Tuple[str, str | None, Dict[str, Any] | None]:
    """Pull the SDP offer (and an optional model and session) out of the body.

    Two shapes are accepted: the raw ``application/sdp`` body the OpenAI
    realtime clients send, and a JSON envelope, which is also what the backend
    itself wants.
    """
    kind = (content_type or "").split(";")[0].strip().lower()
    model: str | None = None
    session: Dict[str, Any] | None = None

    if kind == "application/json":
        try:
            payload: Any = json.loads(raw_body) if raw_body.strip() else {}
        except Exception as exc:
            raise RealtimeRequestError("Invalid JSON body", status_code=400) from exc
        if not isinstance(payload, dict):
            raise RealtimeRequestError("Request body must be a JSON object", status_code=400)
        sdp = payload.get("sdp")
        if not isinstance(sdp, str) or not sdp.strip():
            raise RealtimeRequestError("Missing required parameter: 'sdp'", status_code=400)
        raw_model = payload.get("model")
        if isinstance(raw_model, str) and raw_model.strip():
            model = raw_model.strip()
        if isinstance(payload.get("session"), dict):
            session = dict(payload["session"])
            session_model = session.get("model")
            if model is None and isinstance(session_model, str) and session_model.strip():
                model = session_model.strip()
    elif kind in (SDP_CONTENT_TYPE, "text/plain", ""):
        sdp = raw_body
    else:
        raise RealtimeRequestError(
            f"Unsupported Content-Type '{kind}'. Send the offer as {SDP_CONTENT_TYPE} "
            "or as JSON with an 'sdp' field.",
            status_code=415,
            code="unsupported_content_type",
        )

    if not sdp.lstrip().startswith("v="):
        raise RealtimeRequestError(
            "The body must be a WebRTC SDP offer (it starts with 'v=').",
            status_code=400,
        )
    return sdp, model, session


def build_call_body(offer_sdp: str, *, model: str, session: Dict[str, Any] | None) -> Dict[str, Any]:
    """Shape the offer the way the Codex backend asks for it.

    Measured, not guessed: the endpoint refuses ``application/sdp`` outright
    ("Unsupported content type"), and a JSON body without a ``session`` object
    gets "Field `session` must be an object".
    """
    if isinstance(session, dict):
        # A client that sends its own session gets it through untouched: the
        # live handshake, for one, must NOT carry a "type".
        merged: Dict[str, Any] = dict(session)
    else:
        merged = {"type": "realtime"}
    merged["model"] = model
    return {"sdp": offer_sdp, "session": merged}


# Headers the Codex app sends on a live handshake that ChatMock has no way to
# forge -- the attestation above all. Whatever the client puts there wins over
# the values ChatMock would stamp.
LIVE_PASSTHROUGH_HEADERS = (
    "openai-alpha",
    "originator",
    "user-agent",
    "version",
    "thread-id",
    "session-id",
    "x-session-id",
    "x-oai-attestation",
    "x-codex-turn-metadata",
)


def forward_realtime_live(
    raw_body: bytes,
    *,
    content_type: str | None,
    accept: str | None,
    session_id: str,
    extra_headers: Dict[str, str] | None = None,
    extra_query: Dict[str, str] | None = None,
    timeout: float = 60,
) -> requests.Response:
    """Pass a full-duplex handshake straight through, byte for byte.

    The /live handshake is not the one above and is not documented anywhere, so
    nothing here rewrites it: whatever the client sends is what the backend
    gets.
    """
    access_token, account_id = get_effective_chatgpt_auth()
    if not access_token or not account_id:
        raise RealtimeRequestError(
            "Missing ChatGPT credentials. Run 'python3 chatmock.py login' first.",
            status_code=401,
        )

    def _post(token: str, account: str) -> requests.Response:
        headers = build_upstream_headers(
            token,
            account,
            session_id,
            accept=accept or "application/json",
        )
        # Whatever answers /live is not the Responses API, and the GA realtime
        # endpoints reject the beta header outright.
        headers.pop("OpenAI-Beta", None)
        if content_type:
            headers["Content-Type"] = content_type
        else:
            headers.pop("Content-Type", None)
        for name, value in (extra_headers or {}).items():
            if name.lower() in LIVE_PASSTHROUGH_HEADERS:
                headers[name] = value
        params = {"intent": LIVE_INTENT, "architecture": LIVE_ARCHITECTURE}
        params.update(extra_query or {})
        return requests.post(
            CHATGPT_REALTIME_LIVE_URL,
            headers=headers,
            params=params,
            data=raw_body,
            timeout=timeout,
        )

    try:
        upstream = _post(access_token, account_id)
    except requests.RequestException as exc:
        raise RealtimeRequestError(f"Upstream ChatGPT request failed: {exc}", status_code=502) from exc

    if upstream.status_code == 401:
        refreshed_token, refreshed_account = get_effective_chatgpt_auth(force_refresh=True)
        if refreshed_token and refreshed_account and refreshed_token != access_token:
            try:
                upstream.close()
            except Exception:
                pass
            try:
                upstream = _post(refreshed_token, refreshed_account)
            except requests.RequestException as exc:
                raise RealtimeRequestError(
                    f"Upstream ChatGPT request failed after token refresh: {exc}",
                    status_code=502,
                ) from exc
    return upstream


def build_realtime_websocket_url(model: str | None, extra_query: Dict[str, str] | None = None) -> str:
    params: Dict[str, str] = dict(extra_query or {})
    # A transcription session picks its model inside session.update and refuses
    # the query parameter: "You must not provide a model parameter for
    # transcription sessions."
    if model:
        params["model"] = model
    return f"{CHATGPT_REALTIME_WS_URL}?{urlencode(params)}"


def build_realtime_websocket_headers(access_token: str, account_id: str, session_id: str) -> Dict[str, str]:
    headers = build_upstream_headers(access_token, account_id, session_id, accept="application/json")
    # The GA socket rejects the beta shape outright ("The Realtime Beta API is
    # no longer supported"), and a handshake carries no body.
    headers.pop("OpenAI-Beta", None)
    headers.pop("Content-Type", None)
    return headers


def answer_from_response(body: bytes, content_type: str | None) -> str | None:
    """Return the answer SDP when the backend wraps it in JSON."""
    if "json" not in (content_type or "").lower():
        return None
    try:
        payload = json.loads(body.decode("utf-8", errors="ignore"))
    except Exception:
        return None
    if isinstance(payload, dict):
        for key in ("sdp", "answer", "answer_sdp"):
            value = payload.get(key)
            if isinstance(value, str) and value.lstrip().startswith("v="):
                return value
    return None


def forward_realtime_offer(
    offer_sdp: str,
    *,
    model: str,
    session_id: str,
    session: Dict[str, Any] | None = None,
    extra_query: Dict[str, str] | None = None,
    timeout: float = 60,
) -> requests.Response:
    """Hand the client's SDP offer to the Codex backend and return its answer.

    Only the handshake goes through here. Once the answer is back, audio flows
    straight between the client and OpenAI over WebRTC -- ChatMock never sees a
    media packet.
    """
    access_token, account_id = get_effective_chatgpt_auth()
    if not access_token or not account_id:
        raise RealtimeRequestError(
            "Missing ChatGPT credentials. Run 'python3 chatmock.py login' first.",
            status_code=401,
        )

    params: Dict[str, str] = dict(extra_query or {})
    body = build_call_body(offer_sdp, model=model, session=session)
    # Full duplex rides the same route with intent=quicksilver&architecture=avas,
    # and the backend refuses it without this header: "AVAS requires OpenAI-Alpha:
    # quicksilver=v2".
    wants_live = params.get("intent") == LIVE_INTENT or params.get("architecture") == LIVE_ARCHITECTURE

    def _post(token: str, account: str) -> requests.Response:
        headers = build_upstream_headers(token, account, session_id, accept="application/json")
        if wants_live:
            headers["OpenAI-Alpha"] = QUICKSILVER_ALPHA
        return requests.post(
            CHATGPT_REALTIME_CALLS_URL,
            headers=headers,
            params=params,
            json=body,
            timeout=timeout,
        )

    try:
        upstream = _post(access_token, account_id)
    except requests.RequestException as exc:
        raise RealtimeRequestError(f"Upstream ChatGPT request failed: {exc}", status_code=502) from exc

    if upstream.status_code == 401:
        refreshed_token, refreshed_account = get_effective_chatgpt_auth(force_refresh=True)
        if refreshed_token and refreshed_account and refreshed_token != access_token:
            try:
                upstream.close()
            except Exception:
                pass
            try:
                upstream = _post(refreshed_token, refreshed_account)
            except requests.RequestException as exc:
                raise RealtimeRequestError(
                    f"Upstream ChatGPT request failed after token refresh: {exc}",
                    status_code=502,
                ) from exc
    return upstream
