"""
providers/anthropic_provider.py -- Genera interfaces usando Claude via la
Messages API directa, con "extended thinking" activado.

A diferencia del backend `claude-code` de host.py (que usa el CLI como caja
negra), aqui hablamos la API en streaming: cada delta de pensamiento, cada
tool call y su resultado se emiten como eventos en cuanto ocurren, para que
el frontend los pinte en vivo.
"""

from __future__ import annotations

import json
import os

from anthropic import AsyncAnthropic

from .base import MAX_TURNOS, SYSTEM_PROMPT, anthropic_tool_schema, ejecutar_tool, extraer_html, now_ms

MODELO_POR_DEFECTO = "claude-sonnet-5"
THINKING_BUDGET = 4000
MAX_TOKENS = 8000


class AnthropicProvider:
    nombre = "Claude (API, extended thinking)"

    def __init__(self, modelo: str | None = None):
        self.modelo = modelo or MODELO_POR_DEFECTO
        api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not api_key or api_key in {"sk-ant-...", "tu-key-aqui", "placeholder", '""'}:
            raise RuntimeError(
                "Falta ANTHROPIC_API_KEY en .env para usar el proveedor Claude (API)."
            )
        self.client = AsyncAnthropic(api_key=api_key)

    async def stream(self, prompt: str):
        inicio = now_ms()
        thinking_ms = 0
        tok_in = tok_out = 0
        tools_usadas: list[str] = []
        tools_schema = await anthropic_tool_schema()
        messages: list[dict] = [{"role": "user", "content": prompt}]

        for turno in range(MAX_TURNOS):
            texto_final = ""
            tool_calls: list[dict] = []  # {id, name, buffer: str}
            thinking_started_at: int | None = None
            resultados_tool: list[dict] = []

            async with self.client.messages.stream(
                model=self.modelo,
                max_tokens=MAX_TOKENS,
                thinking={"type": "enabled", "budget_tokens": THINKING_BUDGET},
                system=SYSTEM_PROMPT,
                tools=tools_schema,
                messages=messages,
            ) as stream:
                async for event in stream:
                    if event.type == "content_block_start":
                        if event.content_block.type == "tool_use":
                            tool_calls.append(
                                {"id": event.content_block.id, "name": event.content_block.name, "buffer": ""}
                            )
                        elif event.content_block.type == "thinking":
                            thinking_started_at = now_ms()

                    elif event.type == "content_block_delta":
                        delta = event.delta
                        if delta.type == "thinking_delta":
                            yield {"type": "thinking_delta", "text": delta.thinking}
                        elif delta.type == "text_delta":
                            texto_final += delta.text
                        elif delta.type == "input_json_delta":
                            if tool_calls:
                                tool_calls[-1]["buffer"] += delta.partial_json

                    elif event.type == "content_block_stop":
                        if thinking_started_at is not None:
                            thinking_ms += now_ms() - thinking_started_at
                            thinking_started_at = None
                            yield {"type": "thinking_done", "ms": thinking_ms}

                final_message = await stream.get_final_message()

            tok_in += final_message.usage.input_tokens
            tok_out += final_message.usage.output_tokens
            yield {
                "type": "usage",
                "turn": turno + 1,
                "input_tokens": final_message.usage.input_tokens,
                "output_tokens": final_message.usage.output_tokens,
            }

            messages.append({"role": "assistant", "content": final_message.content})

            if final_message.stop_reason != "tool_use":
                break

            for tc in tool_calls:
                try:
                    args = json.loads(tc["buffer"]) if tc["buffer"] else {}
                except json.JSONDecodeError:
                    args = {}
                yield {"type": "tool_call", "id": tc["id"], "name": tc["name"], "args": args}

                t0 = now_ms()
                salida = ejecutar_tool(tc["name"], args)
                dt_ms = now_ms() - t0
                es_error = isinstance(salida, dict) and "error" in salida
                tools_usadas.append(tc["name"])
                yield {
                    "type": "tool_result",
                    "id": tc["id"],
                    "name": tc["name"],
                    "result": salida,
                    "ms": dt_ms,
                    "error": es_error,
                }
                resultados_tool.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tc["id"],
                        "content": json.dumps(salida, ensure_ascii=False),
                        "is_error": es_error,
                    }
                )

            messages.append({"role": "user", "content": resultados_tool})
        else:
            yield {"type": "error", "message": f"Se alcanzo el limite de {MAX_TURNOS} turnos sin terminar."}
            return

        try:
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
