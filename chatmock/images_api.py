from __future__ import annotations

from typing import Any, Dict, List, Tuple

# Sem import de outro modulo do pacote aqui em cima de proposito: utils.py
# importa este arquivo, e model_catalog -> utils fecha o ciclo. O unico import
# interno fica dentro de collect_images_from_sse.


IMAGE_TOOL_TYPE = "image_generation"

# Modelo de texto que orquestra a chamada. Quem desenha e sempre o
# gpt-image-2-codex do lado do backend; este aqui so escreve o prompt revisado,
# entao o mais barato serve.
DEFAULT_IMAGE_ORCHESTRATOR_MODEL = "gpt-5.4-mini"

# Parametros do tool que o backend aceita hoje. 'n' aparece no echo da resposta
# mas e recusado na entrada ('Unknown parameter: tools[0].n'), por isso nao esta
# aqui: varias imagens sao varias requisicoes.
IMAGE_TOOL_PARAM_KEYS = (
    "size",
    "quality",
    "output_format",
    "output_compression",
    "background",
    "moderation",
)

MAX_IMAGES_PER_REQUEST = 4


def build_image_tool(params: Dict[str, Any] | None) -> Dict[str, Any]:
    tool: Dict[str, Any] = {"type": IMAGE_TOOL_TYPE}
    if isinstance(params, dict):
        for key in IMAGE_TOOL_PARAM_KEYS:
            value = params.get(key)
            if value is None:
                continue
            if isinstance(value, str) and not value.strip():
                continue
            tool[key] = value
    return tool


def size_hint_instruction(size: Any) -> str | None:
    """O backend ignora `size` (devolve sempre "auto" no echo) e escolhe a
    proporcao a partir do prompt. Entao o pedido de tamanho vira instrucao em
    texto, que e a unica via que ele de fato escuta."""
    if not isinstance(size, str):
        return None
    raw = size.strip().lower()
    if not raw or raw == "auto":
        return None
    if "x" not in raw:
        return None
    left, _, right = raw.partition("x")
    try:
        width = int(left)
        height = int(right)
    except ValueError:
        return None
    if width <= 0 or height <= 0:
        return None
    if width == height:
        shape = "quadrada (proporcao 1:1)"
    elif width > height:
        shape = "horizontal (paisagem)"
    else:
        shape = "vertical (retrato)"
    return f"A imagem deve ser {shape}, o mais proximo possivel de {width}x{height} pixels."


def build_image_request_payload(
    prompt: str,
    *,
    model: str,
    tool_params: Dict[str, Any] | None = None,
    input_images: List[str] | None = None,
) -> Dict[str, Any]:
    content: List[Dict[str, Any]] = [{"type": "input_text", "text": prompt}]
    for url in input_images or []:
        if isinstance(url, str) and url.strip():
            content.append({"type": "input_image", "image_url": url})

    instructions = [
        "Voce gera imagens. Chame a ferramenta de imagem uma unica vez com o "
        "pedido do usuario e nao escreva nenhum comentario alem disso."
    ]
    hint = size_hint_instruction((tool_params or {}).get("size"))
    if hint:
        instructions.append(hint)

    return {
        "model": model,
        "instructions": " ".join(instructions),
        "input": [{"type": "message", "role": "user", "content": content}],
        "tools": [build_image_tool(tool_params)],
        "tool_choice": {"type": IMAGE_TOOL_TYPE},
        "parallel_tool_calls": False,
        "store": False,
        "stream": True,
    }


def image_item_to_openai(item: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {"b64_json": item.get("result") or ""}
    revised = item.get("revised_prompt")
    if isinstance(revised, str) and revised.strip():
        out["revised_prompt"] = revised
    for key in ("size", "output_format", "quality", "background"):
        value = item.get(key)
        if value is not None:
            out[key] = value
    return out


def data_url_for_item(item: Dict[str, Any]) -> str | None:
    b64 = item.get("result")
    if not isinstance(b64, str) or not b64:
        return None
    fmt = item.get("output_format") if isinstance(item.get("output_format"), str) else "png"
    return f"data:image/{fmt};base64,{b64}"


def image_markdown_for_item(item: Dict[str, Any]) -> str:
    url = data_url_for_item(item)
    if not url:
        return ""
    alt = item.get("revised_prompt")
    alt = alt.replace("\n", " ").strip()[:120] if isinstance(alt, str) else ""
    return f"\n\n![{alt or 'imagem'}]({url})"


def collect_images_from_sse(
    upstream: Any,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any] | None, Dict[str, Any] | None]:
    """Le o SSE ate o fim e devolve (itens de imagem, usage, erro).

    O `response.completed` do backend do Codex vem com `output: []`, entao os
    itens so existem nos eventos `response.output_item.done` — e por isso que
    esperar pelo objeto final devolve nada."""
    from .responses_api import iter_sse_event_payloads

    images: List[Dict[str, Any]] = []
    usage: Dict[str, Any] | None = None
    error: Dict[str, Any] | None = None
    try:
        for evt in iter_sse_event_payloads(upstream):
            kind = evt.get("type")
            if kind == "response.output_item.done":
                item = evt.get("item")
                if isinstance(item, dict) and item.get("type") == "image_generation_call":
                    images.append(item)
            elif kind == "response.failed":
                response = evt.get("response")
                if isinstance(response, dict) and isinstance(response.get("error"), dict):
                    error = response["error"]
                else:
                    error = {"message": "response.failed"}
                break
            elif kind == "error":
                error = evt.get("error") if isinstance(evt.get("error"), dict) else {"message": "upstream error"}
                break
            elif kind == "response.completed":
                response = evt.get("response")
                if isinstance(response, dict):
                    tool_usage = response.get("tool_usage")
                    if isinstance(tool_usage, dict) and isinstance(tool_usage.get("image_gen"), dict):
                        usage = tool_usage["image_gen"]
                break
    finally:
        try:
            upstream.close()
        except Exception:
            pass
    return images, usage, error


def usage_to_openai(usage: Dict[str, Any] | None) -> Dict[str, Any] | None:
    if not isinstance(usage, dict):
        return None
    try:
        input_tokens = int(usage.get("input_tokens") or 0)
        output_tokens = int(usage.get("output_tokens") or 0)
    except Exception:
        return None
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": int(usage.get("total_tokens") or (input_tokens + output_tokens)),
    }
