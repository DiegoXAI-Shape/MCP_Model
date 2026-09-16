// chat.js -- Controlador del chat: pinta la conversacion, muestra el
// razonamiento y las tool calls en vivo, y mete el HTML final en un iframe
// aislado (sandboxed) para que el estilo de la interfaz generada nunca se
// mezcle ni se sobreponga con el de esta app.

import { streamGenerate } from "./sse.js";

const chatLog = document.getElementById("chat-log");
const composer = document.getElementById("composer");
const promptInput = document.getElementById("prompt-input");
const sendBtn = document.getElementById("send-btn");
const providerSelect = document.getElementById("provider");

const emptyState = document.getElementById("empty-state");
const skeleton = document.getElementById("skeleton");
const preview = document.getElementById("preview");

function fmtMs(ms) {
  if (ms == null) return "";
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}

function fmtNum(n) {
  return (n ?? 0).toLocaleString("es-MX");
}

function scrollToEnd() {
  chatLog.scrollTop = chatLog.scrollHeight;
}

function addUserMessage(text) {
  const wrap = document.createElement("div");
  wrap.className = "msg msg-user";
  const role = document.createElement("div");
  role.className = "msg-role";
  role.textContent = "tu";
  const body = document.createElement("div");
  body.className = "msg-body";
  body.textContent = text;
  wrap.append(role, body);
  chatLog.appendChild(wrap);
  scrollToEnd();
}

function addErrorMessage(text) {
  const wrap = document.createElement("div");
  wrap.className = "msg msg-error";
  wrap.textContent = text;
  chatLog.appendChild(wrap);
  scrollToEnd();
}

// Crea la tarjeta del turno del modelo y devuelve referencias a sus partes
// para irlas actualizando conforme llegan eventos del stream.
function addAssistantTurn() {
  const wrap = document.createElement("div");
  wrap.className = "msg msg-assistant";

  const role = document.createElement("div");
  role.className = "msg-role";
  role.textContent = "modelo";

  const reasoning = document.createElement("details");
  reasoning.className = "reasoning";
  reasoning.open = true;
  const summary = document.createElement("summary");
  summary.innerHTML = "";
  const summaryLabel = document.createElement("span");
  summaryLabel.textContent = "razonamiento";
  const reasoningMs = document.createElement("span");
  reasoningMs.className = "reasoning-ms";
  summary.append(summaryLabel, reasoningMs);
  const reasoningText = document.createElement("pre");
  reasoningText.className = "reasoning-text";
  reasoning.append(summary, reasoningText);

  const toolCalls = document.createElement("div");
  toolCalls.className = "tool-calls";

  const msgSummary = document.createElement("div");
  msgSummary.className = "msg-summary";

  wrap.append(role, reasoning, toolCalls, msgSummary);
  chatLog.appendChild(wrap);
  scrollToEnd();

  return { wrap, reasoningText, reasoningMs, toolCalls, msgSummary };
}

function addToolChip(container, id, name, args) {
  const chip = document.createElement("div");
  chip.className = "tool-chip pending";
  chip.dataset.toolId = id;

  const head = document.createElement("div");
  head.className = "tool-chip-head";
  const nameEl = document.createElement("span");
  nameEl.className = "tool-name";
  nameEl.textContent = name;
  const argsEl = document.createElement("span");
  argsEl.className = "tool-args";
  argsEl.textContent = `(${JSON.stringify(args)})`;
  const statusEl = document.createElement("span");
  statusEl.className = "tool-status";
  statusEl.textContent = "en curso";
  head.append(nameEl, argsEl, statusEl);
  chip.appendChild(head);

  container.appendChild(chip);
  scrollToEnd();
  return chip;
}

function resolveToolChip(container, id, ok, ms, result) {
  const chip = container.querySelector(`[data-tool-id="${CSS.escape(id)}"]`);
  if (!chip) return;
  chip.classList.remove("pending");
  if (!ok) chip.classList.add("error");
  const statusEl = chip.querySelector(".tool-status");
  statusEl.textContent = `${ok ? "ok" : "error"} · ${fmtMs(ms)}`;

  const pre = document.createElement("pre");
  let texto;
  try {
    texto = JSON.stringify(result, null, 2);
  } catch {
    texto = String(result);
  }
  pre.textContent = texto.length > 600 ? `${texto.slice(0, 600)}...` : texto;
  chip.appendChild(pre);
}

function setLoading(isLoading) {
  sendBtn.disabled = isLoading;
  promptInput.disabled = isLoading;
  providerSelect.disabled = isLoading;

  if (isLoading) {
    skeleton.hidden = false;
    emptyState.hidden = true;
  } else {
    skeleton.hidden = true;
  }
}

function showHtml(html) {
  skeleton.hidden = true;
  emptyState.hidden = true;
  preview.hidden = false;
  preview.srcdoc = html;
}

async function onSubmit(event) {
  event.preventDefault();
  const prompt = promptInput.value.trim();
  if (!prompt) return;

  const provider = providerSelect.value;
  addUserMessage(prompt);
  promptInput.value = "";
  setLoading(true);

  const turn = addAssistantTurn();
  let thinkingBuffer = "";
  let gotHtml = false;

  try {
    for await (const evt of streamGenerate(prompt, provider)) {
      switch (evt.type) {
        case "thinking_delta":
          thinkingBuffer += evt.text;
          turn.reasoningText.textContent = thinkingBuffer;
          scrollToEnd();
          break;

        case "thinking_done":
          turn.reasoningMs.textContent = fmtMs(evt.ms);
          break;

        case "tool_call":
          addToolChip(turn.toolCalls, evt.id, evt.name, evt.args);
          break;

        case "tool_result":
          resolveToolChip(turn.toolCalls, evt.id, !evt.error, evt.ms, evt.result);
          break;

        case "html":
          showHtml(evt.html);
          gotHtml = true;
          break;

        case "done": {
          const tk = evt.tokens || {};
          const tools = evt.tools?.length ? evt.tools.join(", ") : "ninguna";
          turn.msgSummary.textContent =
            `${fmtNum(tk.in)} + ${fmtNum(tk.out)} tokens · ` +
            `${fmtMs(evt.thinking_ms)} pensando · ${fmtMs(evt.total_ms)} total · ` +
            `herramientas: ${tools}`;
          break;
        }

        case "error":
          if (!thinkingBuffer) turn.wrap.querySelector(".reasoning").hidden = true;
          addErrorMessage(evt.message);
          break;

        default:
          break;
      }
    }
  } catch (err) {
    addErrorMessage(`Error de conexion: ${err.message}`);
  } finally {
    setLoading(false);
    if (!gotHtml && !preview.srcdoc) {
      preview.hidden = true;
      emptyState.hidden = false;
    }
  }
}

composer.addEventListener("submit", onSubmit);

promptInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    composer.requestSubmit();
  }
});
