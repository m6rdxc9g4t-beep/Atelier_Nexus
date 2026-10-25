import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { sharedPoll } from "./sharedPoll";

/** Source simulée : lectures comptées, visibilité et réveils pilotés par le test. */
function fakeSource(values: number[] = [3]) {
  let visible = true;
  let wake: (() => void) | null = null;
  const signals: AbortSignal[] = [];
  let i = 0;
  const read = vi.fn((signal: AbortSignal) => {
    signals.push(signal);
    const value = values[Math.min(i++, values.length - 1)]!;
    return Promise.resolve(value);
  });
  const unwatch = vi.fn(() => {
    wake = null;
  });
  return {
    source: {
      read,
      intervalMs: 20_000,
      visible: () => visible,
      watch: (w: () => void) => {
        wake = w;
        return unwatch;
      },
    },
    read,
    unwatch,
    signals,
    setVisible: (v: boolean) => {
      visible = v;
    },
    wake: () => wake?.(),
  };
}

describe("lecture périodique partagée", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("ne lit qu'une fois pour tous les abonnés, puis toutes les 20 s", async () => {
    const fake = fakeSource([3, 5]);
    const poll = sharedPoll(fake.source);
    const a = vi.fn();
    const b = vi.fn();
    poll.subscribe(a);
    poll.subscribe(b);
    expect(fake.read).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(0);
    expect(fake.read).toHaveBeenCalledTimes(1);
    expect(poll.get()).toBe(3);
    expect(a).toHaveBeenCalledTimes(1);
    expect(b).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(20_000);
    expect(fake.read).toHaveBeenCalledTimes(2);
    expect(poll.get()).toBe(5);
  });

  it("s'arrête au dernier abonné et repart de zéro", async () => {
    const fake = fakeSource([4]);
    const poll = sharedPoll(fake.source);
    const offA = poll.subscribe(() => undefined);
    const offB = poll.subscribe(() => undefined);
    await vi.advanceTimersByTimeAsync(0);
    offA();
    offA();
    await vi.advanceTimersByTimeAsync(20_000);
    expect(fake.read).toHaveBeenCalledTimes(2);
    offB();
    expect(fake.unwatch).toHaveBeenCalledTimes(1);
    expect(poll.get()).toBeNull();
    await vi.advanceTimersByTimeAsync(60_000);
    expect(fake.read).toHaveBeenCalledTimes(2);
  });

  it("ne lit rien tant que la page est cachée, et relit au réveil", async () => {
    const fake = fakeSource([1, 2]);
    fake.setVisible(false);
    const poll = sharedPoll(fake.source);
    poll.subscribe(() => undefined);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(fake.read).not.toHaveBeenCalled();
    fake.setVisible(true);
    fake.wake();
    await vi.advanceTimersByTimeAsync(0);
    expect(fake.read).toHaveBeenCalledTimes(1);
    expect(poll.get()).toBe(1);
    // Décision ou lancement : relu tout de suite, le minuteur repart
    fake.wake();
    await vi.advanceTimersByTimeAsync(0);
    expect(fake.read).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(19_999);
    expect(fake.read).toHaveBeenCalledTimes(2);
  });

  it("abandonne la lecture précédente et rend null sur une erreur", async () => {
    const fake = fakeSource([7]);
    const poll = sharedPoll(fake.source);
    poll.subscribe(() => undefined);
    await vi.advanceTimersByTimeAsync(0);
    expect(poll.get()).toBe(7);
    fake.read.mockImplementationOnce(() => Promise.reject(new Error("injoignable")));
    fake.wake();
    await vi.advanceTimersByTimeAsync(0);
    expect(fake.signals[0]!.aborted).toBe(true);
    expect(poll.get()).toBeNull();
  });
});
