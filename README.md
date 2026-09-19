<div align="center">

# ChatMock

**Allows Codex to work in your favourite chat apps and coding tools.**

[![PyPI](https://img.shields.io/pypi/v/chatmock?color=blue&label=pypi)](https://pypi.org/project/chatmock/)
[![Python](https://img.shields.io/pypi/pyversions/chatmock)](https://pypi.org/project/chatmock/)
[![License](https://img.shields.io/github/license/RayBytes/ChatMock)](LICENSE)
[![Stars](https://img.shields.io/github/stars/RayBytes/ChatMock?style=flat)](https://github.com/RayBytes/ChatMock/stargazers)
[![Last Commit](https://img.shields.io/github/last-commit/RayBytes/ChatMock)](https://github.com/RayBytes/ChatMock/commits/main)
[![Issues](https://img.shields.io/github/issues/RayBytes/ChatMock)](https://github.com/RayBytes/ChatMock/issues)

<br>


</div>

<br>

## Install

#### Homebrew
```bash
brew tap RayBytes/chatmock
brew install chatmock
```

#### pipx / pip
```bash
pipx install chatmock
```

#### GUI
Download from [releases](https://github.com/RayBytes/ChatMock/releases) (macOS & Windows)

#### Docker
See [DOCKER.md](DOCKER.md)

<br>

## Getting Started

```bash
# 1. Sign in with your ChatGPT account
# If you are running this on a headless server, append --headless
chatmock login

# 2. Start the server
chatmock serve
```


The server runs at `http://127.0.0.1:8000` by default. Use `http://127.0.0.1:8000/v1` as your base URL for OpenAI-compatible apps.

<br>

## Realtime: voice, video and transcription

Your plan already pays for the voice models behind Codex, so ChatMock hands them
to any client you like:

| What | Where |
|---|---|
| Voice, one turn at a time | `POST /v1/realtime/calls` -- the official handshake, bare SDP in, SDP out |
| Voice, full duplex (GPT-Live) | same route with `?intent=quicksilver&architecture=avas` |
| Camera or screen | a video track in the offer, turn-taking mode |
| Transcription only (`whisper-1` & co.) | `ws://…/v1/realtime?intent=transcription` |
| Realtime socket instead of WebRTC | `ws://…/v1/realtime` |

### Voice

The handshake has the same shape as the official docs -- point the base URL at
ChatMock and the sample code runs unchanged:

```js
const res = await fetch("http://127.0.0.1:8000/v1/realtime/calls?model=gpt-realtime-1.5", {
  method: "POST",
  body: offer.sdp,
  headers: { "Content-Type": "application/sdp" },
});
await pc.setRemoteDescription({ type: "answer", sdp: await res.text() });
```

Audio never goes through ChatMock: it brokers the handshake and the media flows
straight between your client and OpenAI.

### Full duplex

Talking over the model while it talks, instead of waiting for it to finish. Same
route, different intent -- and the session must carry no `type`, which is what
picks turn-taking:

```js
await fetch("http://127.0.0.1:8000/v1/realtime/calls?intent=quicksilver&architecture=avas", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    sdp: offer.sdp,
    model: "gpt-live-1-codex",
    session: { delegation: { type: "client" }, audio: { output: { voice: "vale" } } },
  }),
});
```

The two voice modes take **disjoint voice rosters**: full duplex answers to the
ChatGPT voices (`vale`, `arbor`, `breeze`, `cove`, `ember`, `juniper`, `maple`,
`sol`, `spruce`, `glimmer`, `orbit`, `fathom`), turn-taking to the API ones
(`alloy`, `ash`, `ballad`, `coral`, `echo`, `sage`, `shimmer`, `verse`, `marin`,
`cedar`). The wrong list is a flat 403.

### Camera and screen

Turn-taking negotiates video: add a track to the offer and the answer comes back
with it. Camera and screen share are the same thing here -- `getUserMedia` or
`getDisplayMedia`, your pick. Nothing to configure on the server, since the whole
offer is forwarded as it is. Full duplex is audio only and rejects a video
offer.

```js
const screen = await navigator.mediaDevices.getDisplayMedia({ video: true });
pc.addTrack(screen.getVideoTracks()[0], screen);
```

### Transcription

A session that only listens, with no voice model attached. The model is picked
in `session.update`, never in the query:

```js
const ws = new WebSocket("ws://127.0.0.1:8000/v1/realtime?intent=transcription");
ws.onopen = () => ws.send(JSON.stringify({
  type: "session.update",
  session: { type: "transcription", audio: { input: { transcription: { model: "whisper-1" } } } },
}));
// then stream PCM16 with input_audio_buffer.append
```

Accepted models: `whisper-1`, `gpt-realtime-whisper`, `gpt-live-transcribe`,
`gpt-transcribe`, `gpt-4o-transcribe`, `gpt-4o-mini-transcribe`, and two dated
mini builds.

### Try it

Two ready pages, both in `examples/`. Serve the folder over `http://` (not
`file://`) so the browser grants the microphone:

- `realtime_voice.html` -- microphone, live transcript, voice picker, video
  off/camera/screen, and a full-duplex switch.
- `transcribe.html` -- microphone in, text out, with the model picker.

```bash
python -m http.server 8080 --directory examples
```

The undocumented corners -- why the session carries no `type`, which header the
backend demands, what `delegation` accepts -- are written down in
[FORK.md](FORK.md).

<br>

## Example usage

<details>
<summary><strong>Raycast Integration</strong></summary>

1. **Configure the Host URL**  
   Open your Raycast Extensions preferences, navigate to the **Ollama** settings section, and input the host URL (default is `127.0.0.1:8000`).  
   <img width="587" height="211" alt="Raycast Ollama Host URL configuration" src="https://github.com/user-attachments/assets/012c576b-189a-4b96-832d-bb054d484f2b" />

2. **Sync Your Models**  
   Click the **Sync Models** button, which will register all available models.

3. **Start Chatting**  
   Open the Raycast AI Chat interface. You will now see model slugs which you can chat with. 
</details>

<details>
<summary><strong>Terax (Agentic Terminal) Integration</strong></summary>

1. **Configure the provider settings**  
   Open your Terax settings, and switch to the **Models** tab, add a new provider (**OpenAI Compatible**), and input the host URL (default is `http://127.0.0.1:8000/v1`), along with the model IDs you wish to use (API key may be anything).  
   <img width="700" height="337" alt="image" src="https://github.com/user-attachments/assets/d1faf4e2-1969-417d-881e-5fb72f9aa252" />

2. **Favourite, and start using it!** <br>
   Go back to your main chat window, select the model by going to the OpenAI Compatible icon, and clicking the model there (you may favourite it here to quickly select it the next time if you switch between models)
   <img width="456" height="465" alt="image" src="https://github.com/user-attachments/assets/b9d2ba22-5747-4335-b095-8ec0fb2bb30c" />
</details>

<br>

## Supported Models

ChatMock automatically discovers the models available to the signed-in ChatGPT
account. The current catalog commonly includes:

- `gpt-5.6-sol`
- `gpt-5.6-terra`
- `gpt-5.6-luna`
- `gpt-5.5`
- `gpt-5.4`
- `gpt-5.4-mini`
- `gpt-5.3-codex-spark`
- `gpt-6-astra` -- answers when you name it, but the account catalog does not
  advertise it, so it only shows up in `/v1/models` with `--model-sync false`

<br>

## Features

- Tool / function calling
- Vision / image input
- Image generation (`/v1/images/generations`, or as a tool in a chat request)
- Thinking summaries (via think tags)
- Configurable thinking effort
- Fast mode for supported models
- Web search tool
- OpenAI-compatible `/v1/responses` (HTTP + WebSocket)
- Realtime voice: `POST /v1/realtime/calls` (WebRTC handshake) and `ws://.../v1/realtime` (socket relay)
- Full-duplex voice (GPT-Live): same route with `?intent=quicksilver&architecture=avas`
- Camera / screen video into a realtime session, and transcription-only sessions (`whisper-1` and friends)
- Ollama-compatible endpoints
- Reasoning effort exposed as separate models (optional)

<br>

## Configuration

All flags go after `chatmock serve`. These can also be set as environment variables.

| Flag | Env var | Options | Default | Description |
|------|---------|---------|---------|-------------|
| `--reasoning-effort` | `CHATGPT_LOCAL_REASONING_EFFORT` | none, minimal, low, medium, high, xhigh, max, ultra | medium | How hard the model thinks |
| `--reasoning-summary` | `CHATGPT_LOCAL_REASONING_SUMMARY` | auto, concise, detailed, none | auto | Thinking summary verbosity |
| `--reasoning-compat` | `CHATGPT_LOCAL_REASONING_COMPAT` | legacy, o3, think-tags | think-tags | How reasoning is returned to the client |
| `--fast-mode` | `CHATGPT_LOCAL_FAST_MODE` | true/false | false | Priority processing for supported models |
| `--enable-web-search` | `CHATGPT_LOCAL_ENABLE_WEB_SEARCH` | true/false | false | Allow the model to search the web |
| `--expose-reasoning-models` | `CHATGPT_LOCAL_EXPOSE_REASONING_MODELS` | true/false | false | List each reasoning level as its own model |
| `--model-sync` | `CHATGPT_LOCAL_MODEL_SYNC` | true/false | true | Discover account models automatically |
| `--model-refresh-interval` | `CHATGPT_LOCAL_MODEL_REFRESH_INTERVAL` | seconds | 3600 | Refresh interval for model discovery |
| `--image-model` | `CHATGPT_LOCAL_IMAGE_MODEL` | model slug | gpt-5.4-mini | Model that orchestrates image requests |
| `--realtime-model` | `CHATGPT_LOCAL_REALTIME_MODEL` | model slug | gpt-realtime-1.5 | Voice model requested by the realtime routes |

<details>
<summary><b>Web search in a request</b></summary>

```json
{
  "model": "gpt-5.4",
  "messages": [{"role": "user", "content": "latest news on ..."}],
  "responses_tools": [{"type": "web_search"}],
  "responses_tool_choice": "auto"
}
```

</details>

<details>
<summary><b>Generating an image</b></summary>

`/v1/images/generations` mirrors the OpenAI Images API, so existing clients work
unchanged:

```bash
curl http://127.0.0.1:8000/v1/images/generations \
  -H "Content-Type: application/json" \
  -d '{"prompt": "a minimalist geometric fox logo", "size": "1024x1024"}'
```

```json
{ "created": 1786806013,
  "data": [{ "b64_json": "...", "revised_prompt": "...", "size": "1254x1254" }],
  "usage": { "input_tokens": 52, "output_tokens": 915, "total_tokens": 967 } }
```

The same tool works inside a chat request on `/v1/chat/completions` and
`/api/chat`, where the image comes back embedded in the message content as
`![alt](data:image/png;base64,...)`:

```json
{
  "model": "gpt-5.4-mini",
  "messages": [{"role": "user", "content": "draw a blue cube"}],
  "responses_tools": [{"type": "image_generation"}]
}
```

Worth knowing:

- The picture is always drawn by the backend's own image model. `model` in the
  request body changes nothing; it is accepted so clients that always send
  `gpt-image-1` keep working.
- `n` goes up to 4, and each unit is a separate upstream request, because the
  backend refuses `n` inside the tool.
- `size` is passed along but the backend decides the final resolution from the
  prompt, so it is written into the instructions as well. Treat it as a request,
  not a guarantee.
- `response_format: "url"` is rejected: the backend returns base64 and ChatMock
  hosts no files.
- One image is a couple of megabytes of base64. `--verbose` prints request bodies,
  so leave it off when passing reference images.

</details>

<details>
<summary><b>Fast mode in a request</b></summary>

```json
{
  "model": "gpt-5.4",
  "input": "summarize this",
  "fast_mode": true
}
```

</details>

<br>

## Important notice

Use responsibly and at your own risk. This project is not affiliated with OpenAI.

<br>

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=RayBytes/ChatMock&type=Timeline)](https://www.star-history.com/#RayBytes/ChatMock&Timeline)
