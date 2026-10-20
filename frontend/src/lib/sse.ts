/**
 * Lecture d'un flux Server-Sent Events depuis une réponse `fetch`.
 * `EventSource` ne permet pas de POST : on lit le corps à la main.
 */

export interface SseMessage {
  event: string;
  data: string;
}

/**
 * Découpe un tampon texte en messages SSE complets.
 * Renvoie les messages trouvés et le reste (message incomplet) à conserver.
 */
export function parseSseChunk(buffer: string): { messages: SseMessage[]; rest: string } {
  const normalized = buffer.replace(/\r\n?/g, "\n");
  const blocks = normalized.split("\n\n");
  const rest = blocks.pop() ?? "";
  const messages: SseMessage[] = [];
  for (const block of blocks) {
    let event = "message";
    const data: string[] = [];
    for (const line of block.split("\n")) {
      if (!line || line.startsWith(":")) continue; // commentaire / ping
      const colon = line.indexOf(":");
      const field = colon === -1 ? line : line.slice(0, colon);
      let value = colon === -1 ? "" : line.slice(colon + 1);
      if (value.startsWith(" ")) value = value.slice(1);
      if (field === "event") event = value;
      else if (field === "data") data.push(value);
    }
    if (data.length) messages.push({ event, data: data.join("\n") });
  }
  return { messages, rest };
}

/** Itère sur les messages SSE d'un flux d'octets. */
export async function* readSse(stream: ReadableStream<Uint8Array>): AsyncGenerator<SseMessage> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const { messages, rest } = parseSseChunk(buffer);
      buffer = rest;
      yield* messages;
    }
    buffer += decoder.decode();
    if (buffer.trim()) yield* parseSseChunk(buffer + "\n\n").messages;
  } finally {
    reader.releaseLock();
  }
}
