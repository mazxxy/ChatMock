from __future__ import annotations

import json
import os
import ssl
import threading
import uuid
from typing import Any, Dict

import certifi
from flask import current_app, request
from flask_sock import Sock
from websockets.sync.client import connect as websocket_connect
from websockets.exceptions import ConnectionClosed

from .realtime_api import (
    DEFAULT_REALTIME_MODEL,
    build_realtime_websocket_headers,
    build_realtime_websocket_url,
)
from .responses_api import (
    ResponsesRequestError,
    extract_client_session_id,
    normalize_responses_payload,
)
from .session import (
    clear_responses_reuse_state,
    note_responses_stream_event,
    prepare_responses_request_for_session,
)
from .upstream import build_upstream_headers, build_upstream_websocket_url
from .utils import get_effective_chatgpt_auth


def _log_json(prefix: str, payload: Any) -> None:
    try:
        print(f"{prefix}\n{json.dumps(payload, indent=2, ensure_ascii=False)}")
    except Exception:
        try:
            print(f"{prefix}\n{payload}")
        except Exception:
            pass


def _error_event(message: str, *, status_code: int = 400, code: str | None = None) -> Dict[str, Any]:
    error: Dict[str, Any] = {"message": message}
    if code:
        error["code"] = code
    return {"type": "error", "status_code": status_code, "error": error}


def _is_terminal_event(event: Any) -> bool:
    if not isinstance(event, dict):
        return False
    kind = event.get("type")
    return kind in ("response.completed", "response.failed", "error")


def _build_websocket_ssl_context() -> ssl.SSLContext:
    cafile = (
        os.getenv("CODEX_CA_CERTIFICATE")
        or os.getenv("SSL_CERT_FILE")
        or certifi.where()
    )
    return ssl.create_default_context(cafile=cafile)


def connect_upstream_websocket(url: str, headers: Dict[str, str]):
    return websocket_connect(
        url,
        additional_headers=headers,
        open_timeout=15,
        ssl=_build_websocket_ssl_context(),
    )


def register_websocket_routes(sock: Sock) -> None:
    @sock.route("/v1/realtime")
    def realtime_websocket(ws) -> None:
        """Relay a realtime voice session, frame for frame.

        Same shape as the official socket, so a client only swaps the URL. Both
        sides are free to talk at any time: nothing here waits for a turn.
        """
        verbose = bool(current_app.config.get("VERBOSE"))
        model = (
            request.args.get("model")
            or current_app.config.get("REALTIME_MODEL")
            or DEFAULT_REALTIME_MODEL
        )
        extra_query = {k: v for k, v in request.args.items() if k != "model"}

        access_token, account_id = get_effective_chatgpt_auth()
        if not access_token or not account_id:
            evt = _error_event(
                "Missing ChatGPT credentials. Run 'python3 chatmock.py login' first.",
                status_code=401,
            )
            try:
                ws.send(json.dumps(evt))
            except Exception:
                pass
            return

        session_id = extract_client_session_id(request.headers) or uuid.uuid4().hex
        try:
            upstream_ws = connect_upstream_websocket(
                build_realtime_websocket_url(model, extra_query),
                build_realtime_websocket_headers(access_token, account_id, session_id),
            )
        except Exception as exc:
            evt = _error_event(f"Upstream websocket connection failed: {exc}", status_code=502)
            try:
                ws.send(json.dumps(evt))
            except Exception:
                pass
            return

        stop = threading.Event()

        def pump_upstream() -> None:
            # The only thread that writes to the client, so the two directions
            # never race on the same socket.
            try:
                while not stop.is_set():
                    message = upstream_ws.recv()
                    if message is None:
                        break
                    if verbose:
                        try:
                            print("STREAM OUT WS /v1/realtime\n" + str(message)[:2000])
                        except Exception:
                            pass
                    ws.send(message)
            except Exception:
                pass
            finally:
                stop.set()

        pump = threading.Thread(target=pump_upstream, daemon=True)
        pump.start()

        try:
            while not stop.is_set():
                incoming = ws.receive()
                if incoming is None:
                    break
                if verbose:
                    try:
                        print("IN WS /v1/realtime\n" + str(incoming)[:2000])
                    except Exception:
                        pass
                upstream_ws.send(incoming)
        except Exception:
            pass
        finally:
            stop.set()
            try:
                upstream_ws.close()
            except Exception:
                pass
            pump.join(timeout=2)

    @sock.route("/v1/responses")
    def responses_websocket(ws) -> None:
        verbose = bool(current_app.config.get("VERBOSE"))
        upstream_ws = None
        upstream_session_id: str | None = None
        active_session_id: str | None = None

        def _send_error(message: str, *, status_code: int = 400, code: str | None = None) -> None:
            evt = _error_event(message, status_code=status_code, code=code)
            if verbose:
                _log_json("STREAM OUT WS /v1/responses (error)", evt)
            try:
                ws.send(json.dumps(evt))
            except Exception:
                pass

        try:
            while True:
                incoming = ws.receive()
                if incoming is None:
                    break

                if isinstance(incoming, bytes):
                    incoming_text = incoming.decode("utf-8", errors="ignore")
                else:
                    incoming_text = str(incoming)
                if verbose:
                    print("IN WS /v1/responses\n" + incoming_text)

                try:
                    payload = json.loads(incoming_text)
                except Exception:
                    _send_error("Websocket frames must be valid JSON objects.", status_code=400)
                    break

                if not isinstance(payload, dict):
                    _send_error("Websocket frames must be JSON objects.", status_code=400)
                    break

                client_session_id = extract_client_session_id(request.headers)
                outbound_text = incoming_text
                session_id = upstream_session_id

                if payload.get("type") == "response.create":
                    try:
                        normalized = normalize_responses_payload(
                            payload,
                            config=current_app.config,
                            client_session_id=client_session_id,
                        )
                    except ResponsesRequestError as exc:
                        _send_error(str(exc), status_code=exc.status_code, code=exc.code)
                        continue

                    if normalized.service_tier_resolution.warning_message and verbose:
                        print(f"[FastMode] {normalized.service_tier_resolution.warning_message}")
                    prepared = prepare_responses_request_for_session(
                        normalized.session_id,
                        normalized.payload,
                        allow_previous_response_id=True,
                    )
                    outbound_text = json.dumps(prepared.payload)
                    session_id = normalized.session_id
                    active_session_id = normalized.session_id
                    if verbose:
                        _log_json("OUTBOUND >> ChatGPT Responses WS payload", prepared.payload)
                elif upstream_ws is None:
                    _send_error(
                        "The first websocket message must be a response.create request.",
                        status_code=400,
                    )
                    break

                if upstream_ws is None or (session_id and session_id != upstream_session_id):
                    access_token, account_id = get_effective_chatgpt_auth()
                    if not access_token or not account_id:
                        if session_id:
                            clear_responses_reuse_state(session_id)
                        _send_error(
                            "Missing ChatGPT credentials. Run 'python3 chatmock.py login' first.",
                            status_code=401,
                        )
                        break

                    if upstream_ws is not None:
                        try:
                            upstream_ws.close()
                        except Exception:
                            pass

                    effective_session_id = session_id or client_session_id or ""
                    try:
                        upstream_ws = connect_upstream_websocket(
                            build_upstream_websocket_url(),
                            build_upstream_headers(
                                access_token,
                                account_id,
                                effective_session_id,
                                accept="application/json",
                            ),
                        )
                    except Exception as exc:
                        if session_id:
                            clear_responses_reuse_state(session_id)
                        _send_error(
                            f"Upstream websocket connection failed: {exc}",
                            status_code=502,
                        )
                        break
                    upstream_session_id = effective_session_id

                upstream_ws.send(outbound_text)

                while True:
                    try:
                        upstream_message = upstream_ws.recv()
                    except ConnectionClosed:
                        if active_session_id:
                            clear_responses_reuse_state(active_session_id)
                        _send_error("Upstream websocket closed unexpectedly.", status_code=502)
                        return
                    if upstream_message is None:
                        if active_session_id:
                            clear_responses_reuse_state(active_session_id)
                        _send_error("Upstream websocket closed unexpectedly.", status_code=502)
                        return
                    if verbose:
                        try:
                            print("STREAM OUT WS /v1/responses\n" + str(upstream_message))
                        except Exception:
                            pass
                    ws.send(upstream_message)

                    try:
                        parsed = json.loads(upstream_message)
                    except Exception:
                        parsed = None
                    if isinstance(parsed, dict) and active_session_id:
                        note_responses_stream_event(active_session_id, parsed)
                    if _is_terminal_event(parsed):
                        if isinstance(parsed, dict) and parsed.get("type") in ("response.failed", "error"):
                            if upstream_ws is not None:
                                try:
                                    upstream_ws.close()
                                except Exception:
                                    pass
                            upstream_ws = None
                            upstream_session_id = None
                        break
        finally:
            if upstream_ws is not None:
                try:
                    upstream_ws.close()
                except Exception:
                    pass
