# Panel de Cartera Generativo

Servidor **MCP** sobre una cartera de cobranza sintética, con un **host que
genera interfaces mínimas bajo demanda**: se le pregunta en lenguaje natural
por el estado de la cartera y devuelve una página HTML autónoma —KPIs, gráficas
SVG, tablas— construida al momento con los datos reales de la consulta.

Proyecto pensado para el dominio de **cobranza / cuentas por cobrar**: aging de
cartera, recovery rate, promesas de pago, desempeño por gestor.

```
┌────────────────────┐   ┌──────────────────────┐   ┌───────────────────────────┐
│ Datos sintéticos   │   │ Servidor MCP         │   │ Host de interfaces        │
│ (SQLite)           │──▶│ server.py            │──▶│ host.py                   │
│ seed.py            │   │ 7 tools tipadas      │   │ Claude (vía MCP) → HTML   │
│ deudores, cuentas, │   │ sobre tools_core.py  │   │ out/<n>.html + galería    │
│ pagos, promesas    │   │                      │   │                           │
└────────────────────┘   └──────────┬───────────┘   └───────────────────────────┘
                                    │
                         MCP Inspector / Claude Desktop
                         (mismo servidor, cliente interactivo)
```

`tools_core.py` es la **única fuente de verdad**: tanto el servidor MCP como el
host la reutilizan; las pruebas la cubren directamente.

## Puesta en marcha

```bash
python -m venv venv
venv\Scripts\pip install -e ".[dev]"     # Windows  (Linux/Mac: venv/bin/pip)
python seed.py                            # crea cobranza.db (reproducible, semilla fija)
pytest -q                                 # 10 pruebas
```

### Servidor MCP

```bash
python server.py            # modo stdio
mcp dev server.py           # abre el MCP Inspector (requiere Node)
python scripts/probe_mcp.py # cliente stdio mínimo: lista y llama las tools
```

### Host de interfaces

Dos motores (`--backend`):

```bash
# claude-code (por defecto): usa el CLI `claude` como cliente MCP.
# No necesita API key; corre con la sesión de Claude Code ya autenticada.
python host.py "Dame un resumen ejecutivo de la cartera"
python host.py --demo                       # genera 4 interfaces de ejemplo

# api: llama directo a la Messages API. Necesita ANTHROPIC_API_KEY en .env
python host.py --backend api "¿Qué gestor recupera más?"
```

Cada interfaz se guarda en `out/`, y `out/index.html` es una galería de todo lo
generado. En `docs/ejemplos/` están las 4 interfaces del `--demo` ya generadas
(ábrelas en el navegador sin tener que correr nada).

## Herramientas MCP

| Tool | Parámetros | Devuelve |
|---|---|---|
| `portfolio_summary` | — | Saldo vivo y vencido, % de cartera vencida, mora promedio ponderada, recuperado 30 d, % de promesas cumplidas |
| `aging` | — | Cartera viva por bucket (`al_corriente`, `1-30`, `31-60`, `61-90`, `90+`): saldo, cuentas, % del total |
| `list_accounts` | `bucket?`, `gestor_id?`, `estatus?`, `orden`, `limite` | Cuentas con datos del deudor y del gestor |
| `get_account` | `cuenta_id` | Detalle de una cuenta + historial de pagos y promesas |
| `get_debtor` | `deudor_id` | Perfil del deudor con todas sus cuentas y su saldo en mora |
| `cashflow` | `desde?`, `hasta?`, `granularidad` | Monto cobrado por periodo (día / semana / mes) |
| `collector_stats` | `desde?`, `hasta?` | Ranking de gestores: saldo gestionado, recuperado, % de promesas |

Los errores de entrada (cuenta inexistente, bucket inválido, rango de fechas al
revés) se devuelven como `{"error": "..."}`, no como excepción de transporte.

## Cálculos de cobranza

- **Bucket de aging**: clasificación de la cuenta por `días_de_mora`.
- **% de cartera vencida** (por saldo): `saldo_en_mora / saldo_vivo`.
- **Días de mora promedio ponderados por saldo**:

  ```
  Σ (saldo_i · días_mora_i) / Σ saldo_i
  ```

- **Recovery rate 30 d**: `recuperado_últimos_30d / (saldo_vencido + recuperado_últimos_30d)`.
- **% de promesas cumplidas**: `promesas_cumplidas / promesas_totales`.

La fecha de corte de los datos está fija en **2026-09-01** (`HOY` en `seed.py`
y `tools_core.py`) para que todo sea reproducible.

## Capturas

| | |
|---|---|
| MCP Inspector: lista de tools | `docs/img/inspector-tools.png` |
| MCP Inspector: llamada con resultado | `docs/img/inspector-call.png` |
| Interfaz generada: resumen ejecutivo | `docs/img/ui-resumen.png` |
| Interfaz generada: aging | `docs/img/ui-aging.png` |
| Galería `out/index.html` | `docs/img/galeria.png` |

## Decisiones técnicas

- **`tools_core` separado del servidor MCP.** El protocolo (esquemas, transporte)
  y la lógica de negocio viven aparte. El host reusa la lógica sin volver a
  pasar por el transporte MCP; las pruebas atacan funciones puras.
- **Backend `claude-code` por defecto.** Demuestra el servidor MCP con un
  cliente real y no exige que quien clone el repo tenga saldo de API.
- **Datos sintéticos con semilla fija.** La base se regenera igual en cualquier
  máquina y en CI, así las pruebas pueden afirmar valores exactos.
- **El modelo solo ve herramientas de solo lectura.** No hay forma de que una
  interfaz generada modifique la cartera.

## Con más tiempo

- `score_account`: probabilidad de pago a 30 días con regresión logística
  (features: días de mora, promesas rotas, pagos parciales recientes).
- Harness de evals de *tool-choice*: N preguntas con las tools esperadas,
  para medir si el modelo elige bien.
- Host web (FastAPI) con chat + `<iframe>` en vivo, en vez de archivos en `out/`.
- Empaquetar el servidor para `claude mcp add` / `claude_desktop_config.json`.

## Estructura

```
seed.py            generador de la cartera sintética (SQLite)
tools_core.py      lógica de negocio — 7 funciones puras
server.py          servidor MCP (envuelve tools_core)
host.py            genera interfaces (backend claude-code | api)
scripts/probe_mcp.py   cliente MCP de prueba
tests/test_tools.py    10 pruebas sobre una cartera de 5 cuentas
mcp.config.json    config del servidor MCP para el CLI `claude`
out/               interfaces generadas + galería (no versionado)
```
