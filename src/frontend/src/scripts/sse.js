// sse.js -- Cliente minimo de streaming para /api/generate.
//
// No usamos EventSource porque necesitamos mandar un POST con body (prompt +
// proveedor). En su lugar leemos el body de fetch como stream y parseamos a
// mano el formato "data: {...}\n\n" de Server-Sent Events.

export async function* streamGenerate(prompt, provider, modelo) {
  const resp = await fetch("/api/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt, provider, modelo: modelo || null }),
  });

  if (!resp.ok || !resp.body) {
    yield { type: "error", message: `El servidor respondio HTTP ${resp.status}` };
    return;
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let sepIndex;
    while ((sepIndex = buffer.indexOf("\n\n")) !== -1) {
      const raw = buffer.slice(0, sepIndex);
      buffer = buffer.slice(sepIndex + 2);

      const dataLine = raw.split("\n").find((l) => l.startsWith("data:"));
      if (!dataLine) continue;

      const payload = dataLine.slice(5).trim();
      try {
        yield JSON.parse(payload);
      } catch {
        // linea mal formada: se ignora en vez de tronar el stream completo
      }
    }
  }
}
