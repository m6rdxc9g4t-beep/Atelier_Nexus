import { describe, expect, it } from "vitest";

import { parseSseChunk, readSse } from "./sse";

const encoder = new TextEncoder();

function streamOf(...chunks: string[]): ReadableStream<Uint8Array> {
  return new ReadableStream({
    start(controller) {
      for (const c of chunks) controller.enqueue(encoder.encode(c));
      controller.close();
    },
  });
}

describe("parseSseChunk", () => {
  it("découpe les messages complets et garde le reste", () => {
    const { messages, rest } = parseSseChunk(
      'event: text_delta\ndata: {"text":"Bon"}\n\nevent: done\ndata: {"a"',
    );
    expect(messages).toEqual([{ event: "text_delta", data: '{"text":"Bon"}' }]);
    expect(rest).toBe('event: done\ndata: {"a"');
  });

  it("gère CRLF, commentaires (ping) et données multilignes", () => {
    const { messages } = parseSseChunk(": ping\r\n\r\nevent: x\r\ndata: a\r\ndata: b\r\n\r\n");
    expect(messages).toEqual([{ event: "x", data: "a\nb" }]);
  });
});

describe("readSse", () => {
  it("reconstitue des messages coupés entre deux paquets, y compris en UTF-8", async () => {
    const accent = encoder.encode('event: text_delta\ndata: {"text":"é"}\n\n');
    const cut = accent.length - 5; // au milieu du caractère « é » encodé sur 2 octets
    const stream = new ReadableStream<Uint8Array>({
      start(c) {
        c.enqueue(accent.slice(0, cut));
        c.enqueue(accent.slice(cut));
        c.close();
      },
    });
    const out = [];
    for await (const m of readSse(stream)) out.push(m);
    expect(out).toEqual([{ event: "text_delta", data: '{"text":"é"}' }]);
  });

  it("lit un dernier message sans ligne vide finale", async () => {
    const out = [];
    for await (const m of readSse(streamOf("event: done\ndata: {}"))) out.push(m);
    expect(out).toEqual([{ event: "done", data: "{}" }]);
  });
});
