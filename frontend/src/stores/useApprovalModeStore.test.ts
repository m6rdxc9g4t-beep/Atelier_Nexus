import { beforeEach, describe, expect, it, vi } from "vitest";

import type { SettingsView } from "@/types/api";

const settings = vi.fn<() => Promise<SettingsView>>();

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, api: { settings: () => settings() } };
});

const { useApprovalModeStore } = await import("./useApprovalModeStore");

const view = (value: string): SettingsView => ({
  env_file: "/x/.env",
  fields: [
    {
      key: "APPROVAL_MODE",
      label: "",
      group: "Validation des actions",
      kind: "choice",
      help: "",
      choices: ["every_step", "writes_only"],
      value,
      configured: true,
      hint: null,
      source: "fichier",
    },
  ],
});

describe("réglage APPROVAL_MODE dans l'interface", () => {
  beforeEach(() => {
    useApprovalModeStore.setState({ mode: "every_step", status: "idle" });
    settings.mockReset();
  });

  it("part de « chaque action », lit le réglage puis suit les Réglages enregistrés", async () => {
    expect(useApprovalModeStore.getState().mode).toBe("every_step");
    settings.mockResolvedValue(view("writes_only"));
    await useApprovalModeStore.getState().load();
    expect(useApprovalModeStore.getState()).toMatchObject({ mode: "writes_only", status: "ready" });
    useApprovalModeStore.getState().fromSettings(view("every_step"));
    expect(useApprovalModeStore.getState().mode).toBe("every_step");
  });

  it("réglage illisible : garde le plus prudent", async () => {
    settings.mockRejectedValue(new Error("hors ligne"));
    await useApprovalModeStore.getState().load();
    expect(useApprovalModeStore.getState()).toMatchObject({ mode: "every_step", status: "ready" });
  });
});
