# MCP Cobranza (Sandbox)

Entorno de pruebas (*sandbox*) y prueba de concepto para la consulta y análisis de una cartera de cobranza mediante el protocolo **Model Context Protocol (MCP)**.

Actualmente el proyecto funciona a través de **interfaz de línea de comandos (CLI)** e interactúa con **Claude** (ya sea mediante el CLI de Claude Code o la API directa) para consultar métricas financieras y generar vistas HTML bajo demanda.

```
┌─────────────────────────┐     ┌────────────────────────┐     ┌─────────────────────────────┐
│ Base de Datos SQLite    │     │ Servidor MCP           │     │ Host / Orquestador          │
│ (cobranza.db)           │────▶│ (server.py)            │────▶│ (host.py)                   │
│ Datos sintéticos        │     │ 7 herramientas tipadas │     │ Claude (CLI / API)          │
│ seed.py                 │     │ sobre tools_core.py    │     │ Generación de HTML (out/)   │
└─────────────────────────┘     └───────────┬────────────┘     └─────────────────────────────┘
                                            │
                                 Clientes MCP compatibles
                                 (Claude Desktop / Inspector)
```

---

## Alcance y Estado Actual (Sandbox)

* **Entorno controlado:** Utiliza datos sintéticos generados con `Faker (es_MX)` que simulan deudores, gestores, cuentas con distintos niveles de morosidad, pagos y promesas de pago.
* **Operación por CLI:** La interacción actual se realiza desde terminal (`host.py`, `server.py`, `scripts/probe_mcp.py`).
* **Herramientas de solo lectura:** Las consultas permiten inspeccionar y calcular métricas sin modificar el estado de la base de datos.
* **Generación bajo demanda:** Claude interpreta preguntas en lenguaje natural, consulta el servidor MCP y genera reportes en HTML/SVG independientes guardados localmente en `out/`.

### Escalabilidad Futura

La arquitectura separa estrictamente la lógica de datos (`tools_core.py`) del transporte MCP (`server.py`) y del host (`host.py`), lo que permite escalar el proyecto hacia:
1. **Interfaz Gráfica Completa (GUI / Web App):** Integración con frameworks como FastAPI/Node.js en el backend y React/Vue para un panel interactivo en tiempo real con chat y visualizaciones dinámicas.
2. **Conexión a Bases de Datos Reales:** Sustitución de SQLite por motores relacionales empresariales (PostgreSQL, SQL Server, Oracle) con carteras de producción.
3. **Modelos Predictivos:** Incorporación de modelos de Machine Learning (ej. scoring de probabilidad de pago a 30 días, propensión de contacto).
4. **Herramientas de Escritura:** Registro de nuevas promesas de pago, reasignación de cuentas a gestores y conciliación de pagos.

---

## Herramientas MCP Disponibles

El servidor expone 7 herramientas analíticas:

| Herramienta | Parámetros | Descripción |
| :--- | :--- | :--- |
| `portfolio_summary` | Ninguno | Resumen general: saldo vivo, saldo vencido, % cartera vencida, mora ponderada, monto recuperado en 30 días y tasa de promesas cumplidas. |
| `aging` | Ninguno | Distribución de la cartera en buckets de morosidad (`al_corriente`, `1-30`, `31-60`, `61-90`, `90+`). |
| `list_accounts` | `bucket`, `gestor_id`, `estatus`, `orden`, `limite` | Consulta de cuentas con datos del deudor y gestor, con filtros y ordenamiento. |
| `get_account` | `cuenta_id` | Detalle 360° de una cuenta: crédito, deudor, score buró e historial de pagos y promesas. |
| `get_debtor` | `deudor_id` | Perfil consolidado del deudor con todas sus cuentas y saldo total vs en mora. |
| `cashflow` | `desde`, `hasta`, `granularidad` | Flujo de cobranza agrupado por día, semana o mes en un rango de fechas. |
| `collector_stats` | `desde`, `hasta` | Desempeño por gestor: saldo gestionado, monto recuperado y % de promesas cumplidas. |

---

## Métricas y Fórmulas del Dominio

* **% Cartera Vencida:**
  $$\text{Pct Vencida} = \frac{\text{Saldo en mora}}{\text{Saldo vivo total}} \times 100$$
* **Días de Mora Promedio Ponderados por Saldo:**
  $$\text{Mora Ponderada} = \frac{\sum (\text{Saldo}_i \times \text{Días Mora}_i)}{\sum \text{Saldo}_i}$$
* **Recovery Rate (30 días):**
  $$\text{Recovery Rate} = \frac{\text{Recuperado (últimos 30d)}}{\text{Saldo Vencido} + \text{Recuperado (últimos 30d)}} \times 100$$
* **Efectividad de Promesas:**
  $$\text{Cumplimiento} = \frac{\text{Promesas Cumplidas}}{\text{Promesas Totales}} \times 100$$

> **Fecha de corte:** Fijada en `2026-09-01` en `seed.py` y `tools_core.py` para garantizar reproducibilidad en las consultas y pruebas.

---

## Instalación y Uso

### 1. Requisitos Previos
* Python 3.10 o superior.
* Entorno virtual recomendado.

### 2. Configuración del Entorno
```bash
# Crear y activar entorno virtual
python -m venv venv
venv\Scripts\activate       # En Windows
# source venv/bin/activate  # En Linux/macOS

# Instalar dependencias en modo editable
pip install -e ".[dev]"

# Generar la base de datos sintética
python seed.py
```

### 3. Ejecución de Pruebas
```bash
pytest
```

---

## Modos de Ejecución (CLI)

### A. Probar el Servidor MCP Directamente
```bash
# Modo estándar (stdio)
python server.py

# Cliente de prueba (smoke test de las 7 herramientas)
python scripts/probe_mcp.py

# Usando MCP Inspector (requiere Node.js)
mcp dev server.py
```

### B. Generar Interfaces con el Host
El host soporta dos backends:

```bash
# 1. Backend claude-code (por defecto):
# Utiliza la sesión activa del CLI de Claude (no requiere API key manual).
python host.py "Dame un resumen ejecutivo de la cartera"

# Generar lote de 4 interfaces de prueba
python host.py --demo

# 2. Backend API directa (requiere ANTHROPIC_API_KEY en archivo .env):
python host.py --backend api "¿Cuáles son los 3 gestores con mayor recuperación?"
```

Los archivos generados se guardan en la carpeta `out/` junto con un índice interactivo en `out/index.html`. 

*(En `docs/ejemplos/` se incluyen 4 dashboards pre-generados listos para visualizar en el navegador sin ejecutar llamadas).*

---

## Estructura del Repositorio

```text
├── .github/workflows/ci.yml   # Pipeline de CI (seed + pytest)
├── docs/
│   ├── CAPTURAS.md            # Guía de capturas de pantalla
│   └── ejemplos/              # Dashboards HTML de demostración
├── scripts/
│   └── probe_mcp.py           # Cliente de prueba MCP vía stdio
├── tests/
│   └── test_tools.py          # Pruebas unitarias de lógica y métricas
├── conftest.py                # Configuración de rutas de prueba
├── host.py                    # Orquestador y generador de interfaces HTML
├── mcp.config.json            # Configuración para clientes MCP
├── pyproject.toml             # Metadatos del proyecto y dependencias
├── seed.py                    # Generador de datos sintéticos (SQLite)
├── server.py                  # Servidor MCP con transporte stdio
└── tools_core.py              # Lógica de negocio y consultas SQL puras
```
