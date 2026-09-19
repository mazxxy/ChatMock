from __future__ import annotations

import os


CLIENT_ID_DEFAULT = os.getenv("CHATGPT_LOCAL_CLIENT_ID") or "app_EMoamEEZ73f0CkXaXp7hrann"
OAUTH_ISSUER_DEFAULT = os.getenv("CHATGPT_LOCAL_ISSUER") or "https://auth.openai.com"
OAUTH_TOKEN_URL = f"{OAUTH_ISSUER_DEFAULT}/oauth/token"
ORIGINATOR = "chatmock"

CHATGPT_CODEX_BASE_URL = "https://chatgpt.com/backend-api/codex"
CHATGPT_RESPONSES_URL = f"{CHATGPT_CODEX_BASE_URL}/responses"
CHATGPT_REALTIME_CALLS_URL = os.getenv("CHATGPT_LOCAL_REALTIME_CALLS_URL") or f"{CHATGPT_CODEX_BASE_URL}/realtime/calls"
# Full duplex (GPT-Live) is the same URL as above with a different intent: the
# Codex app posts multipart to ...?intent=quicksilver&architecture=avas.
CHATGPT_REALTIME_LIVE_URL = os.getenv("CHATGPT_LOCAL_REALTIME_LIVE_URL") or CHATGPT_REALTIME_CALLS_URL
LIVE_INTENT = os.getenv("CHATGPT_LOCAL_REALTIME_LIVE_INTENT") or "quicksilver"
LIVE_ARCHITECTURE = os.getenv("CHATGPT_LOCAL_REALTIME_LIVE_ARCHITECTURE") or "avas"
QUICKSILVER_ALPHA = os.getenv("CHATGPT_LOCAL_QUICKSILVER_ALPHA") or "quicksilver=v2"
# The WebRTC handshake lives under the Codex backend, but the realtime socket
# itself is the public GA endpoint -- which takes the very same Codex token.
CHATGPT_REALTIME_WS_URL = os.getenv("CHATGPT_LOCAL_REALTIME_WS_URL") or "wss://api.openai.com/v1/realtime"
