import { describe, expect, it } from "vitest";

import { readAgentLink, withoutAgentLink } from "./deepLink";

describe("lien profond vers un agent", () => {
  it("lit le nom de l'agent", () => {
    expect(readAgentLink("?agent=data_analyst")).toBe("data_analyst");
    expect(readAgentLink("?x=1&agent=chef-de-projet")).toBe("chef-de-projet");
  });

  it("ignore un lien absent ou invalide", () => {
    expect(readAgentLink("")).toBeNull();
    expect(readAgentLink("?agent=")).toBeNull();
    expect(readAgentLink("?agent=../etc")).toBeNull();
    expect(readAgentLink(`?agent=${"a".repeat(65)}`)).toBeNull();
  });

  it("retire seulement son paramètre", () => {
    expect(withoutAgentLink("https://nexus.exemple.fr/?agent=redacteur")).toBe("/");
    expect(withoutAgentLink("http://127.0.0.1:3100/?a=1&agent=x#y")).toBe("/?a=1#y");
  });
});
