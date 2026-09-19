# Fork: imagem e voz ao vivo no ChatMock

Fork de [RayBytes/ChatMock](https://github.com/RayBytes/ChatMock) (v1.40) com dois
acréscimos: **imagem** (abaixo) e **voz ao vivo por WebRTC** (no fim do arquivo).

O padrão dos dois é o mesmo: o backend do Codex já sabia fazer — quem não sabia
pedir era o ChatMock. As seções até "Rebase" são sobre imagem.

O backend do Codex já sabia desenhar — quem não sabia receber era o ChatMock.

## O que foi descoberto

O endpoint `https://chatgpt.com/backend-api/codex/responses`, o mesmo que o
ChatMock já usava para texto, aceita o tool `image_generation` e devolve a imagem
em base64. Medido, não deduzido:

- modelo que desenha: `gpt-image-2-codex` (não dá para trocar);
- `tool_choice: {"type": "image_generation"}` funciona e força a geração;
- o consumo aparece em `tool_usage.image_gen` da resposta — ou seja, **sai da
  cota do plano ChatGPT/Codex**, não de crédito de API;
- `n` no tool é recusado (`Unknown parameter: 'tools[0].n'`): uma imagem por
  requisição;
- `size` e `quality` são aceitos mas ignorados — o echo volta sempre `"auto"`.
  A resolução é escolhida a partir do prompt: pedindo 1024x1024 veio 1254x1254,
  pedindo 1536x1024 veio 1536x1024 na mosca. Ou seja, dá para pedir — só não dá
  para garantir.

## O bug que estava por baixo

`response.completed` do backend do Codex vem com `output: []`. Sempre. Os itens
de saída só existem nos eventos `response.output_item.done`.

Como `aggregate_response_from_sse()` devolvia o objeto do evento final, **todo
`POST /v1/responses` com `stream: false` respondia com output vazio** — inclusive
para texto puro, sem imagem nenhuma. A resposta parecia bem-sucedida (`status:
completed`, `usage` preenchido) e não tinha conteúdo.

Corrigido em `chatmock/responses_api.py`: os itens são acumulados por
`output_index` e remontados no objeto final quando ele vem vazio.

## O que mudou

| Arquivo | Mudança |
|---|---|
| `chatmock/images_api.py` | **novo** — monta o payload e converte para o formato da Images API. Sem import interno de propósito: `utils.py` importa este módulo, e `model_catalog -> utils` fecharia o ciclo |
| `chatmock/responses_api.py` | remonta `output` a partir dos `output_item.done` (o bug acima); `collect_images_from_sse()`, que fica aqui porque é este o módulo que já lê SSE |
| `chatmock/routes_openai.py` | rota `/v1/images/generations`; `image_generation` liberado em `responses_tools`; imagem vira data-url no `/v1/chat/completions` |
| `chatmock/utils.py` | imagem como delta de conteúdo no chat streaming, **depois** de fechar o `<think>` — o fechamento virou o helper `_close_think_tag()`, usado nos três pontos que antes repetiam o mesmo bloco |
| `chatmock/app.py`, `chatmock/cli.py` | flag `--image-model` / env `CHATGPT_LOCAL_IMAGE_MODEL` |
| `tests/test_routes.py` | 8 testes novos |

## Uso

```bash
python chatmock.py serve --port 8000
```

### `POST /v1/images/generations`

Compatível com a Images API da OpenAI, então SDK oficial, n8n e afins falam com
ela sem adaptação:

```bash
curl http://127.0.0.1:8000/v1/images/generations \
  -H "Content-Type: application/json" \
  -d '{"prompt":"logo minimalista de uma raposa geometrica","size":"1024x1024"}'
```

```json
{ "created": 1786806013,
  "data": [{ "b64_json": "...", "revised_prompt": "...", "size": "1254x1254" }],
  "usage": { "input_tokens": 52, "output_tokens": 915, "total_tokens": 967 } }
```

Parâmetros:

- `prompt` — obrigatório.
- `n` — de 1 a 4. Cada unidade é **uma requisição a mais** na sua cota, porque o
  backend não aceita `n` no tool.
- `size` — vira instrução em texto ("quadrada", "horizontal", "vertical" +
  os pixels pedidos), já que o backend ignora o parâmetro. Trate como pedido,
  não como garantia: a proporção costuma sair certa, a resolução exata não.
- `quality`, `output_format`, `output_compression`, `background`, `moderation` —
  repassados ao tool. Se o backend recusar algum com `unknown_parameter`, a
  requisição é refeita uma vez com o tool pelado, para o cliente receber a imagem
  em vez de um 400.
- `image` — data-url (ou lista delas) para usar como referência. Não é a
  `/v1/images/edits` multipart da OpenAI, é um atalho em JSON.
- `chat_model` — troca o modelo que orquestra só nesta chamada.
- `response_format: "url"` responde 400: a imagem vem em base64 e o ChatMock não
  hospeda arquivo — igual ao comportamento do `gpt-image-1` na API real.

### Pelo `/v1/chat/completions`

```json
{ "model": "gpt-5.4-mini",
  "messages": [{"role": "user", "content": "gere uma imagem de um cubo azul"}],
  "responses_tools": [{"type": "image_generation"}] }
```

A imagem chega embutida no `content` como `![alt](data:image/png;base64,...)`,
em streaming ou não. Serve para UIs de chat que renderizam markdown.

Com `--reasoning-compat think-tags` (o padrão), a imagem sai **depois** do
`</think>`. Sem isso ela cairia dentro do bloco de raciocínio e sumiria em
qualquer cliente que esconde o `<think>` — que é justamente o motivo do modo
existir.

## Limites conhecidos

- **Peso.** Uma imagem passa de 2,5 MB em base64. Não ligue `--verbose` nessas
  rotas: o log imprime o corpo inteiro.
- Rotas Ollama (`/api/chat`) não foram tocadas — continuam só texto.
- O modelo de imagem é escolhido pelo backend. `model` no corpo da requisição não
  troca nada; existe para não quebrar cliente que sempre manda `gpt-image-1`.

## Rebase

As mudanças em arquivos que já existiam são pequenas e localizadas — o grosso
está em `images_api.py`, que é arquivo novo. Ao subir de versão, os pontos de
atrito são `aggregate_response_from_sse()`, os dois trechos de
`response.output_item.done` (em `routes_openai.py` e `utils.py`) e o
`_close_think_tag()`, que substituiu duas cópias de um bloco que o upstream
repetia dentro de `sse_translate_chat()`.

Comentários e mensagens de erro do código estão em inglês, como o resto do
repositório — só este arquivo está em português.

# Voz ao vivo (WebRTC)

O `/voice` que apareceu no Codex CLI 0.155.0 fala com um endpoint que a mesma
credencial do ChatMock já alcança. A rota `POST /v1/realtime/calls` entrega ao
cliente uma sessão de voz ao vivo paga pela assinatura, **sem crédito de API**.

## O que foi medido

Tudo abaixo saiu de requisição, não de documentação:

- `POST https://chatgpt.com/backend-api/codex/realtime/calls` aceita o mesmo
  `Authorization` + `ChatGPT-Account-ID` das outras rotas.
- **Não é `application/sdp`.** Mandando o SDP cru o backend responde
  `{"detail":"Unsupported content type"}`. Ele quer JSON:

  ```json
  { "sdp": "<oferta>", "session": { "type": "realtime", "model": "gpt-realtime-1.5" } }
  ```

  Sem o `session`: `{"detail":"Field 'session' must be an object"}`. Com outro
  nome no lugar de `sdp`: `{"detail":"Field 'sdp' must be a string"}`. As
  mensagens foram o mapa do esquema.
- A resposta é `201` com o SDP cru em `text/plain` e o `Location` apontando para
  a chamada (`/v1/realtime/calls/rtc_u0_...`).
- **Não existe chave efêmera aqui.** `POST .../codex/realtime/client_secrets` dá
  401 sem token e **404 com token** — a autenticação é o token da conta mesmo.
- **Não é WebSocket.** O upgrade WS só passa em `/codex/responses`; todo
  `/codex/realtime*` devolve 403. O transporte é WebRTC.
- Modelos que o `codex.exe` carrega: `gpt-realtime-1.5` e `gpt-live-1-codex`.

## O que mudou

| Arquivo | Mudança |
|---|---|
| `chatmock/realtime_api.py` | **novo** — valida a oferta, monta `{sdp, session}`, acrescenta o header alpha no modo duplex, fala com o backend e refaz o login em 401 |
| `chatmock/routes_openai.py` | rotas `POST /v1/realtime/calls` e `/v1/realtime/calls/live`; repassam status, corpo e `Location`; desembrulham o SDP se a resposta vier em JSON |
| `chatmock/websocket_routes.py` | rota `ws://.../v1/realtime` — relay frame a frame, com uma thread só escrevendo para o cliente |
| `chatmock/config.py` | `CHATGPT_REALTIME_CALLS_URL`, `CHATGPT_REALTIME_WS_URL`, e o trio do duplex (`LIVE_INTENT`, `LIVE_ARCHITECTURE`, `QUICKSILVER_ALPHA`), todos sobrescritíveis por env |
| `chatmock/http.py` | `Access-Control-Expose-Headers`, senão o browser não lê o `Location` |
| `chatmock/app.py`, `chatmock/cli.py` | flag `--realtime-model` / env `CHATGPT_LOCAL_REALTIME_MODEL` |
| `examples/realtime_voice.html` | página de teste: microfone, transcrição ao vivo, caixa de texto, VAD semântico e chave de full duplex |
| `tests/test_routes.py` | 8 testes novos |

## Dois transportes

O WebRTC (acima) é o caminho do `/voice` do Codex. Mas o socket GA da OpenAI
**aceita o mesmo token do Codex**, o que rende o segundo transporte:

- `ws://127.0.0.1:8000/v1/realtime?model=gpt-realtime-1.5` → relay para
  `wss://api.openai.com/v1/realtime`, com o `Authorization` da assinatura.
- O header `OpenAI-Beta: responses=experimental` que o ChatMock manda nas outras
  rotas **tem que sair** aqui: o socket GA responde
  `The Realtime Beta API is no longer supported`. Por isso a rota monta os
  headers com `build_realtime_websocket_headers()`.
- Serve para cliente que fala o protocolo de socket da documentação oficial e
  para mandar áudio PCM sem WebRTC.

## Uso

A chamada tem **a mesma estrutura da documentação oficial** — o exemplo da OpenAI
roda trocando só a URL de base:

```js
const pc = new RTCPeerConnection();
pc.ontrack = (e) => { audioEl.srcObject = e.streams[0]; };
pc.addTrack(mic.getAudioTracks()[0]);
pc.createDataChannel("oai-events");
await pc.setLocalDescription(await pc.createOffer());

const r = await fetch("http://127.0.0.1:8000/v1/realtime/calls?model=gpt-realtime-1.5", {
  method: "POST",
  body: pc.localDescription.sdp,
  headers: { Authorization: "Bearer qualquer-coisa", "Content-Type": "application/sdp" },
});
await pc.setRemoteDescription({ type: "answer", sdp: await r.text() });
```

O `Authorization` é ignorado, como no resto do ChatMock — o cliente pode mandar a
chave efêmera que o código oficial manda, não faz diferença. A tradução para o
JSON que o backend exige acontece aqui dentro.

Quem preferir JSON também pode mandar `{"sdp": "...", "model": "...", "session":
{...}}`: o `session` é mesclado (o `type` entra sozinho), e o `model` da query
ganha do `model` do corpo. Qualquer outro parâmetro da query é repassado.

Para ver funcionando: `python chatmock.py serve --port 8000`, sirva a pasta
`examples/` (`python -m http.server 8080`) e abra `realtime_voice.html` — sem
microfone ela entra em modo só-escuta e você conversa pela caixa de texto.

## Full duplex (GPT-Live)

Falar por cima do modelo enquanto ele fala — o modo do app de desktop. **Mesma
URL do handshake normal**, o que muda são dois parâmetros de query, um header e
a ausência de um campo:

```
POST https://chatgpt.com/backend-api/codex/realtime/calls?intent=quicksilver&architecture=avas
OpenAI-Alpha: quicksilver=v2

{ "sdp": "<oferta>",
  "session": { "model": "gpt-live-1-codex",
               "delegation": { "type": "client" },
               "audio": { "output": { "voice": "vale" } },
               "instructions": "..." } }
```

Pelo ChatMock:

```js
await fetch("http://127.0.0.1:8000/v1/realtime/calls?intent=quicksilver&architecture=avas", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ sdp: pc.localDescription.sdp, model: "gpt-live-1-codex",
                         session: { delegation: { type: "client" } } }),
});
```

Resposta: `201`, `Location: /v1/realtime/calls/rtc_u0_...`, e o canal de dados
abre com `{"type":"session.started","session":{"id":"rtc_u0_...","status":"active"}}`
— protocolo diferente do turn-taking, que manda `session.created`.

Três detalhes que fazem toda a diferença:

1. **`session` sem `type`.** Mandar `"type": "realtime"` é o que força o modo
   turn-taking e faz o backend recusar: `Model "gpt-live-1-codex" is not
   supported in realtime mode`. Por isso `build_call_body()` repassa o `session`
   do cliente intacto e só resolve o `model`.
2. **`intent` e `architecture` são query, não corpo.** Como campo do `session`,
   `intent` nem é lido; no socket GA (`?intent=`) só valem `realtime` e
   `transcription`.
3. **Sem o header alpha não passa:** `AVAS requires OpenAI-Alpha: quicksilver=v2`.
   A rota acrescenta sozinha quando vê `intent=quicksilver` ou
   `architecture=avas`.

### Vozes

As duas listas são **disjuntas**, e a errada não dá erro parecido:

| Modo | Vozes | Erro com a lista errada |
|---|---|---|
| Duplex (`gpt-live-1-codex`) | `vale`, `arbor`, `breeze`, `cove`, `ember`, `juniper`, `maple`, `sol`, `spruce`, `glimmer`, `orbit`, `fathom` — as do ChatGPT | 403 `Voice session access denied`, sem dizer o motivo |
| Turn-taking (`gpt-realtime-1.5`) | `alloy`, `ash`, `ballad`, `coral`, `echo`, `sage`, `shimmer`, `verse`, `marin`, `cedar` — as da API | 400 que **enumera** as aceitas |

Nome inventado no duplex também cai em 403, então o 403 ali significa "essa voz
não existe neste modo", não "sua conta não tem acesso".

No duplex a voz vai no `session` do próprio handshake
(`audio.output.voice`). No turn-taking, como o handshake é o SDP cru da
documentação, ela entra no `session.update` que a página manda ao abrir o canal.

### Vídeo (câmera e tela)

O turn-taking **negocia vídeo**. Oferecendo `m=video` no SDP, a resposta volta
`201` com `m=video 9 UDP/TLS/RTP/SAVPF ...` e payloads H264 — porta não zerada,
ou seja, aceito de verdade. Serve para câmera (`getUserMedia`) e para tela
(`getDisplayMedia`), que do lado do WebRTC são a mesma coisa.

Não precisou de nada no ChatMock: vídeo é negociação de SDP, e a rota repassa a
oferta inteira. Quem decide é o cliente — a página de exemplo tem o seletor
`Video: off / camera / screen`.

O duplex **não aceita**: com `m=video` na oferta, o handshake morre em 403
`Voice session access denied`, o mesmo erro genérico da voz inválida.

### Transcrição (whisper e afins)

`?intent=transcription` abre uma sessão de transcrição pura, sem modelo de voz:

```
ws://127.0.0.1:8000/v1/realtime?intent=transcription
```

O modelo entra depois, no `session.update`:

```json
{ "type": "session.update",
  "session": { "type": "transcription",
    "audio": { "input": { "transcription": { "model": "whisper-1" } } } } }
```

Aceitos (o backend enumera quando você erra): `whisper-1`,
`gpt-realtime-whisper`, `gpt-live-transcribe`, `gpt-transcribe`,
`gpt-4o-transcribe`, `gpt-4o-mini-transcribe`, `gpt-4o-mini-transcribe-2025-03-20`,
`gpt-4o-mini-transcribe-2025-12-15`.

Pegadinha: a sessão de transcrição **recusa `model` na query**
("You must not provide a model parameter for transcription sessions"), então a
rota de socket omite o padrão quando vê `intent=transcription`.

### Delegação

O `session.delegation.type` do duplex aceita `client` e `responses`. Com
`client`, o modelo de voz espera que **o seu cliente** execute o trabalho pesado
(é o `SpawnThinking` das instruções do app). Com `responses`, ele exige
`delegation.responses.model` — e aí a chamada volta 403
`Voice session access denied`, testado com `gpt-5.6-sol` e `gpt-6-astra`. Ou
seja: existe, mas está fechado para esta credencial.

### Como isso apareceu

Adivinhação não chegou lá — foram ~40 combinações de `intent`, modelo,
originator e header, todas recusadas. O que resolveu foi fazer o próprio app
falar pelo ChatMock: apontando

```toml
experimental_realtime_webrtc_call_base_url = "http://127.0.0.1:8000/v1/realtime/calls"
```

no `~/.codex/config.toml`, o app passou a bater aqui, e o log do ChatMock em
`--verbose` entregou o corpo (multipart `sdp` + `session`) e os headers
(`OpenAI-Alpha: quicksilver=v2`, `Originator: Codex Desktop`, `X-Oai-Attestation`).
A URL final veio do log do próprio app (`~/.codex/logs_2.sqlite`):
`url=https://chatgpt.com/backend-api/codex/realtime/calls?intent=quicksilver&architecture=avas`.

A atestação **não é necessária** para a chamada — só para o edge aceitar o
header alpha vindo de um cliente qualquer; com o token do Codex e os headers
normais do ChatMock, a chamada passa. A rota `/v1/realtime/calls/live` existe
para o caso de o cliente ser o próprio app (corpo multipart, headers repassados
inclusive a atestação).

### Turn-taking com corte (a alternativa)

No modo normal (`gpt-realtime-1.5`) dá para chegar perto com VAD semântico, que
é o que a página liga sozinha:

```json
{ "type": "session.update",
  "session": { "type": "realtime",
    "audio": { "input": { "turn_detection": {
      "type": "semantic_vad", "eagerness": "high", "interrupt_response": true } } } } }
```

Você fala, ele cala na hora. Não é ouvir e falar ao mesmo tempo — para isso, o
duplex acima.

## Limites conhecidos

- **O áudio não passa pelo ChatMock.** Ele só corretora o SDP; a mídia vai direto
  do cliente para a OpenAI. Servidor caído no meio da conversa não derruba a
  chamada.
- Endpoint não documentado e marcado como experimental no próprio Codex: pode
  mudar sem aviso.
- A cota aparece no evento `rate_limits.updated` do canal de dados, não nos
  headers que o `chatmock.py info` lê.
- `size`/`voice` e afins não foram mapeados. O que foi testado é o caminho do
  `session` — o resto é experimentação pela query, que a rota repassa de graça.
