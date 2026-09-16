# Resumen Completo del Proyecto: Panel Generativo de Cobranza

## 1. ¿De dónde veníamos y qué construimos?
El objetivo principal fue construir un **Panel de Cartera Inteligente y Generativo** para cobranza: un sistema donde un usuario (gestor, supervisor o CEO) escribe preguntas en lenguaje natural ("*Dame un resumen de la cartera*", "*Muéstrame las cuentas en mora de 61 a 90 días*", "*Registra una promesa de pago*", "*Dame una tabla con las promesas registradas*") y el sistema:
1. Consulta o modifica la base de datos real SQLite (`cobranza.db`).
2. Utiliza herramientas estándar bajo el protocolo **MCP** (Model Context Protocol).
3. Genera en tiempo real una **interfaz gráfica interactiva y estilizada** (HTML/CSS) renderizada en un sandbox seguro (`<iframe>`).

---

## 2. Arquitectura del Sistema

```text
Usuario (Navegador)
       │  http://localhost:4321
       ▼
Frontend (Astro + Vanilla JS) ───[SSE Stream /api/generate]───► Backend (FastAPI :8787)
                                                                       │
                                                       ┌───────────────┴───────────────┐
                                                       ▼                               ▼
                                            Ollama (GPU Local)                MCP Tools Core (9 herramientas)
                                            Modelo: qwen3.5:16k                         │
                                            (16k contexto en VRAM)                      ▼
                                                                               SQLite (cobranza.db)
```

### Componentes Principales:
1. **Base de Datos y Herramientas Modulares (`src/backend/tools/`)**:
   - `database.py`: Conexión robusta a `cobranza.db` con resolución dinámica de la ruta raíz (`REPO_ROOT`).
   - `portfolio.py`: `portfolio_summary` (KPIs globales) y `aging` (cubetas de mora de 1-30 hasta 180+ días).
   - `accounts.py`: `list_accounts` (búsqueda con filtros sanitizados y tope seguro), `get_account` y `get_debtor`.
   - `analytics.py`: `cashflow` (pagos proyectados vs realizados) y `collector_stats` (rendimiento por gestor/equipo).
   - `information_in.py`: `register_payment_promise` (escritura en BD) y `list_payment_promises` (consulta de promesas).
2. **Servidor MCP (`src/backend/server.py`)**:
   - Expone las 9 herramientas por stdio con sanitización de tipos y argumentos.
3. **Servidor Web y Streaming (`src/backend/web.py`)**:
   - FastAPI sirviendo Server-Sent Events (SSE) con eventos: `thinking_delta`, `thinking_done`, `tool_call`, `tool_result`, `usage`, `html`, `done`, `error`.
4. **Frontend Moderno (`src/frontend/`)**:
   - Astro con tema oscuro, selector de modelos, visualización de razonamiento en vivo, chips de ejecución de herramientas con tiempos de respuesta y previsualizador en vivo con `<iframe>`.

---

## 3. La Odisea con el Modelo Local (Qwen 3.5 en Ollama)

Al trabajar con un modelo local corriendo 100% en tu GPU (evitando costos de APIs externas como Claude o OpenAI), nos enfrentamos a las particularidades y "mañas" típicas de los LLMs pequeños con razonamiento (SLMs):

### Desafío 1: El cuello de botella del contexto de 4k
- **Problema**: El modelo `qwen3.5:4b` viene por defecto con 4,096 tokens de contexto. Al enviar el System Prompt, la pregunta y el resultado JSON de varias herramientas, la entrada consumía ~3,300 tokens, dejando solo ~700 tokens para generar el HTML. El modelo se quedaba sin aire y cortaba el `<style>` a la mitad.
- **Solución**: Creamos un `Modelfile` con `PARAMETER num_ctx 16384` y compilamos en Ollama el modelo `qwen3.5:16k`. Ahora corre holgado con 16k tokens de contexto ocupando ~3.6 GB de VRAM en tu GPU.

### Desafío 2: Argumentos con comillas dobles anidadas
- **Problema**: Qwen a veces generaba argumentos de herramientas como `{"bucket": "\"61-90\""}` con comillas literales escapadas.
- **Solución**: Blindamos todas las herramientas en `accounts.py`, `portfolio.py`, `information_in.py` y `server.py` con sanitización `.strip("\"' ")`.

### Desafío 3: El protocolo de roles de OpenAI
- **Problema**: Intentar recordarle instrucciones al modelo inyectando un mensaje de rol `user` justo después de la respuesta de una herramienta (`role: tool`) rompía la plantilla de chat de Ollama.
- **Solución**: Mantener el flujo canónico estricto: `system` ➔ `user` ➔ `assistant` (tool_call) ➔ `tool` (tool_result) ➔ `assistant` (HTML).

### Desafío 4: El "Overthinking" y la pantalla blanca ("No se recibió respuesta")
- **Problema**: Al consultar las promesas de pago (20 registros con 10 campos cada uno), Qwen activó su modo de razonamiento (`<think> ... </think>`). Se pasó **1,486 tokens filosofando** y analizando promesa por promesa dentro de su pensamiento (el 83% del tiempo). Al terminar de pensar, o emitió stop o redactó su conclusión adentro sin emitir contenido al canal normal (`delta["content"]` quedó vacío). El backend interpretaba que no había respuesta y mostraba el fallback de error.
- **Solución en 4 capas**:
  1. **Regla anti-overthinking en el System Prompt**: Se le indicó que su razonamiento debe ser de máximo 2 líneas de planeación y que NUNCA redacte HTML dentro del `<think>`. El tiempo de pensamiento bajó de 9.2 segundos a menos de 1 segundo (891 ms).
  2. **Rescate de HTML en el pensamiento**: Si el modelo por error escribe el bloque ````html ... ```` dentro de `<think>`, el backend lo busca y lo rescata automáticamente en vez de rendirse.
  3. **Segundo empujón**: Si el modelo gasta su turno pensando y no emite contenido, el backend le solicita de inmediato el bloque HTML para no dejar la pantalla en blanco.
  4. **Condición de herramientas blindada**: Se desacopló la condición de corte de `finish_reason`, asegurando que si hay herramientas pendientes (`calls`), siempre se ejecuten.

---

## 4. Estado Final y Verificación

- **Pruebas Unitarias**: 12/12 pruebas pasando (`pytest tests/`).
- **Servicios Activos**:
  - FastAPI: `http://127.0.0.1:8787` (con `--reload` activo).
  - Astro: `http://localhost:4321`.
  - Ollama: `http://localhost:11434` (modelo `qwen3.5:16k` listo en GPU).
- **Herramientas Disponibles**: 9 herramientas cubriendo lectura integral y registro de promesas de pago.
