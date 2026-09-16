"""
web.py -- API web del panel generativo de cobranza (backend del frontend Astro).

Expone /api/generate: dado un prompt, corre el loop de tool-use contra el
proveedor de modelo elegido (Claude via API directa, o un modelo local via
llama.cpp) y transmite el proceso completo -- razonamiento, llamadas a
herramientas, tokens -- como Server-Sent Events, terminando con el HTML
generado.

Ejecutar:
    uvicorn src.backend.web:app --reload --port 8787
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

try:
    from .providers import PROVIDERS
except ImportError:
    from providers import PROVIDERS

REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env")

app = FastAPI(title="Panel de Cartera Generativo -- API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4321", "http://127.0.0.1:4321"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class GenerarBody(BaseModel):
    prompt: str
    provider: str = "claude"
    modelo: str | None = None


@app.get("/")
def root() -> dict:
    return {
        "status": "online",
        "servicio": "API Backend de Cobranza (FastAPI)",
        "frontend": "http://localhost:4321",
        "docs": "http://127.0.0.1:8787/docs",
        "health": "http://127.0.0.1:8787/api/health",
    }


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "providers": list(PROVIDERS)}


def _sse(evento: dict) -> str:
    return f"data: {json.dumps(evento, ensure_ascii=False)}\n\n"


@app.post("/api/generate")
async def generate(body: GenerarBody):
    fabrica = PROVIDERS.get(body.provider)
    if fabrica is None:
        async def error_unico():
            yield _sse({"type": "error", "message": f"proveedor desconocido: {body.provider!r}"})

        return StreamingResponse(error_unico(), media_type="text/event-stream")

    async def eventos():
        try:
            proveedor = fabrica(body.modelo)
        except RuntimeError as exc:
            yield _sse({"type": "error", "message": str(exc)})
            return

        try:
            async for evento in proveedor.stream(body.prompt):
                yield _sse(evento)
        except Exception as exc:  # ultima red de seguridad: nunca tronar el stream a medias
            yield _sse({"type": "error", "message": f"error inesperado: {exc}"})

    return StreamingResponse(
        eventos(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("web:app", host="127.0.0.1", port=8787, reload=True)
