"""
providers -- Adaptadores de modelo para el panel web generativo.

Cada proveedor expone la misma forma: un generador asincrono de eventos
(dicts JSON-serializables) que narra en vivo lo que el modelo va haciendo
(razonamiento, llamadas a herramientas, tokens) y termina con el HTML
generado. Esto permite que el frontend hable un solo protocolo de eventos
sin importar si el modelo es Claude (API directa) o un modelo local servido
por llama.cpp.
"""

from __future__ import annotations

from .anthropic_provider import AnthropicProvider
from .llamacpp_provider import LlamaCppProvider

PROVIDERS = {
    "claude": AnthropicProvider,
    "qwen-local": LlamaCppProvider,
}

__all__ = ["PROVIDERS", "AnthropicProvider", "LlamaCppProvider"]
