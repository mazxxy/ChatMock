from __future__ import annotations

from flask import Response, jsonify, request


def build_cors_headers() -> dict:
    origin = request.headers.get("Origin", "*")
    req_headers = request.headers.get("Access-Control-Request-Headers")
    allow_headers = req_headers if req_headers else "Authorization, Content-Type, Accept"
    return {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
        "Access-Control-Allow-Headers": allow_headers,
        # A browser cannot read these off a cross-origin response unless they
        # are named here, and /v1/realtime/calls answers with both.
        "Access-Control-Expose-Headers": "Location, X-Upstream-Request-Id",
        "Access-Control-Max-Age": "86400",
    }


def json_error(message: str, status: int = 400) -> Response:
    resp = jsonify({"error": {"message": message}})
    response: Response = Response(response=resp.response, status=status, mimetype="application/json")
    for k, v in build_cors_headers().items():
        response.headers.setdefault(k, v)
    return response

