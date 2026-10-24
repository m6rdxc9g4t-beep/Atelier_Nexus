import { beforeEach, describe, expect, it } from "vitest";

import { useNavStore } from "./useNavStore";

describe("navigation de l'écran principal", () => {
  beforeEach(() => useNavStore.setState({ view: "home", drawerOpen: false }));

  it("s'ouvre sur l'accueil", () => {
    expect(useNavStore.getState().view).toBe("home");
  });

  it("changer de vue referme le tiroir", () => {
    useNavStore.getState().setDrawerOpen(true);
    useNavStore.getState().setView("agents");
    expect(useNavStore.getState()).toMatchObject({ view: "agents", drawerOpen: false });
  });
});
