"""
providers/llamacpp_provider.py -- Genera interfaces usando un modelo local
(pensado para Qwen3/3.5) servido por `llama-server` (llama.cpp), a traves de
su endpoint compatible con OpenAI (/v1/chat/completions).

Requiere que ya tengas corriendo `llama-server` con un modelo que soporte
tool calling y que separe el razonamiento con `--reasoning-format deepseek`
(asi el streaming trae `delta.reasoning_content` ademas de `delta.content`).
Configura la URL y el nombre del modelo con LLAMACPP_BASE_URL / LLAMACPP_MODEL
en .env si tu servidor no usa los valores por defecto.

Este proveedor es "best effort": el soporte de tool calling en llama.cpp
depende bastante de la plantilla de chat del modelo cargado. Si tu servidor
no devuelve `tool_calls` bien formados, el error se reporta como evento
"error" en vez de tronar el proceso.
"""

from __future__ import annotations

import json
import os

import httpx

from .base import MAX_TURNOS, SYSTEM_PROMPT, ejecutar_tool, extraer_html, now_ms, openai_tool_schema

BASE_URL = "http://localhost:11434"
MODELO_POR_DEFECTO = "qwen3.5:16k"


class LlamaCppProvider:
    nombre = "Qwen local (Ollama / llama.cpp)"

    def __init__(self, modelo: str | None = None):
        self.base_url = os.environ.get("LLAMACPP_BASE_URL", BASE_URL).rstrip("/")
        self.modelo = modelo or os.environ.get("LLAMACPP_MODEL", MODELO_POR_DEFECTO)

    async def stream(self, prompt: str):
        inicio = now_ms()
        thinking_ms = 0
        tok_in = tok_out = 0
        tools_usadas: list[str] = []
        tools_schema = await openai_tool_schema()
        messages: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        texto_final = ""
        razonamiento_acumulado = ""

        async with httpx.AsyncClient(timeout=180) as client:
            for turno in range(MAX_TURNOS):
                texto_final = ""
                thinking_started_at: int | None = None
                calls: dict[int, dict] = {}
                finish_reason: str | None = None

                payload: dict = {
                    "model": self.modelo,
                    "messages": messages,
                    "stream": True,
                    "stream_options": {"include_usage": True},
                    "max_tokens": 8192,
                    "options": {
                        "num_predict": 8192,
                        "num_ctx": 16384,
                        "temperature": 0.2,
                    },
                }
                # Solo incluimos tools en el primer turno para no quemar tokens de contexto
                # una vez que el modelo ya tiene los datos y solo debe redactar el HTML.
                if turno == 0:
                    payload["tools"] = tools_schema

                try:
                    async with client.stream(
                        "POST",
                        f"{self.base_url}/v1/chat/completions",
                        json=payload,
                    ) as resp:
                        if resp.status_code >= 400:
                            cuerpo = await resp.aread()
                            yield {
                                "type": "error",
                                "message": f"llama.cpp respondio {resp.status_code}: "
                                f"{cuerpo.decode(errors='replace')[:300]}",
                            }
                            return

                        async for linea in resp.aiter_lines():
                            linea = linea.strip()
                            if not linea or not linea.startswith("data:"):
                                continue
                            payload = linea[len("data:") :].strip()
                            if payload == "[DONE]":
                                break
                            try:
                                chunk = json.loads(payload)
                            except json.JSONDecodeError:
                                continue

                            if chunk.get("usage"):
                                u = chunk["usage"]
                                tok_in = u.get("prompt_tokens", tok_in)
                                tok_out = u.get("completion_tokens", tok_out)

                            choices = chunk.get("choices") or []
                            if not choices:
                                continue
                            choice = choices[0]
                            delta = choice.get("delta") or {}
                            if choice.get("finish_reason"):
                                finish_reason = choice["finish_reason"]

                            razonamiento = delta.get("reasoning_content") or delta.get("reasoning")
                            if razonamiento:
                                if thinking_started_at is None:
                                    thinking_started_at = now_ms()
                                razonamiento_acumulado += razonamiento
                                yield {"type": "thinking_delta", "text": razonamiento}

                            if delta.get("content"):
                                if thinking_started_at is not None:
                                    thinking_ms += now_ms() - thinking_started_at
                                    thinking_started_at = None
                                    yield {"type": "thinking_done", "ms": thinking_ms}
                                texto_final += delta["content"]

                            for tc in delta.get("tool_calls") or []:
                                idx = tc.get("index", 0)
                                slot = calls.setdefault(idx, {"id": None, "name": "", "arguments": ""})
                                if tc.get("id"):
                                    slot["id"] = tc["id"]
                                fn = tc.get("function") or {}
                                if fn.get("name"):
                                    slot["name"] += fn["name"]
                                if fn.get("arguments"):
                                    slot["arguments"] += fn["arguments"]
                except httpx.ConnectError:
                    yield {
                        "type": "error",
                        "message": f"No se pudo conectar al servidor local en {self.base_url}. "
                        "Verifica que Ollama esté corriendo en tu sistema o revisa LLAMACPP_BASE_URL en .env.",
                    }
                    return
                except httpx.HTTPError as exc:
                    yield {"type": "error", "message": str(exc)}
                    return

                if thinking_started_at is not None:
                    thinking_ms += now_ms() - thinking_started_at

                yield {"type": "usage", "turn": turno + 1, "input_tokens": tok_in, "output_tokens": tok_out}

                if not calls:
                    # Si no hubo tool calls y no hubo contenido en delta["content"],
                    # pero el modelo escribió HTML dentro del pensamiento (<think>), rescatarlo:
                    if not texto_final.strip() and razonamiento_acumulado.strip():
                        candidato = extraer_html(razonamiento_acumulado)
                        if "No se recibió respuesta" not in candidato:
                            texto_final = razonamiento_acumulado
                            break

                    # Si el modelo consumió el turno pensando y no escribió HTML, pedirle el HTML:
                    if not texto_final.strip() and turno < MAX_TURNOS - 1:
                        messages.append({"role": "user", "content": "Genera el código HTML dentro de ```html ... ``` para mostrar la interfaz."})
                        continue

                    break

                llamadas = []
                for idx in sorted(calls):
                    c = calls[idx]
                    cid = c["id"] or f"call_{idx}"
                    llamadas.append(
                        {"id": cid, "type": "function", "function": {"name": c["name"], "arguments": c["arguments"]}}
                    )
                messages.append({"role": "assistant", "content": texto_final or None, "tool_calls": llamadas})

                for c in llamadas:
                    nombre = c["function"]["name"]
                    try:
                        args = json.loads(c["function"]["arguments"]) if c["function"]["arguments"] else {}
                    except json.JSONDecodeError:
                        args = {}
                    yield {"type": "tool_call", "id": c["id"], "name": nombre, "args": args}

                    t0 = now_ms()
                    salida = ejecutar_tool(nombre, args)
                    dt_ms = now_ms() - t0
                    es_error = isinstance(salida, dict) and "error" in salida
                    tools_usadas.append(nombre)
                    yield {
                        "type": "tool_result",
                        "id": c["id"],
                        "name": nombre,
                        "result": salida,
                        "ms": dt_ms,
                        "error": es_error,
                    }
                    messages.append(
                        {"role": "tool", "tool_call_id": c["id"], "content": json.dumps(salida, ensure_ascii=False)}
                    )
            else:
                yield {"type": "error", "message": f"Se alcanzo el limite de {MAX_TURNOS} turnos sin terminar."}
                return

        try:
            if not texto_final.strip() and razonamiento_acumulado.strip():
                candidato = extraer_html(razonamiento_acumulado)
                if "No se recibió respuesta" not in candidato:
                    texto_final = razonamiento_acumulado
            html = extraer_html(texto_final)
        except ValueError as exc:
            yield {"type": "error", "message": str(exc)}
            return

        yield {"type": "html", "html": html}
        yield {
            "type": "done",
            "total_ms": now_ms() - inicio,
            "thinking_ms": thinking_ms,
            "tokens": {"in": tok_in, "out": tok_out},
            "tools": sorted(set(tools_usadas)),
        }
