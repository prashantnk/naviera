// frontend/src/hooks/use-single-flight.test.ts
import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useSingleFlight } from "./use-single-flight";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe("useSingleFlight", () => {
  it("drops a second call while the first is in flight", async () => {
    const { result } = renderHook(() => useSingleFlight());
    const gate = deferred<string>();
    const action = vi.fn(() => gate.promise);

    let first!: Promise<string | undefined>;
    let second!: Promise<string | undefined>;
    act(() => {
      first = result.current.run(action);
      second = result.current.run(action);
    });

    expect(action).toHaveBeenCalledTimes(1);
    expect(result.current.pending).toBe(true);
    await expect(second).resolves.toBeUndefined();

    await act(async () => {
      gate.resolve("ok");
      await first;
    });
    await expect(first).resolves.toBe("ok");
    expect(result.current.pending).toBe(false);
  });

  it("exposes the running key and clears it after failure", async () => {
    const { result } = renderHook(() => useSingleFlight());
    const gate = deferred<void>();
    let run!: Promise<void | undefined>;

    act(() => {
      run = result.current.run(() => gate.promise, "row-7");
    });
    expect(result.current.pendingKey).toBe("row-7");

    await act(async () => {
      gate.reject(new Error("boom"));
      await run.catch(() => undefined);
    });
    await expect(run).rejects.toThrow("boom");
    expect(result.current.pending).toBe(false);
    expect(result.current.pendingKey).toBeNull();

    const again = vi.fn(async () => "second");
    await act(async () => {
      await result.current.run(again);
    });
    expect(again).toHaveBeenCalledTimes(1);
  });
});
