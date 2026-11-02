// frontend/src/components/providers/server-wakeup-provider.test.tsx
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  FAILURES_BEFORE_BANNER,
  HEALTH_CHECK_TIMEOUT_MS,
  KEEP_ALIVE_INTERVAL_MS,
  RETRY_INTERVAL_MS,
  ServerWakeupProvider,
  nextWakeupDecision,
} from "./server-wakeup-provider";

describe("nextWakeupDecision (F-03)", () => {
  it("waits at least 10 s and 2 failures before warning", () => {
    expect(HEALTH_CHECK_TIMEOUT_MS).toBeGreaterThanOrEqual(10_000);
    expect(FAILURES_BEFORE_BANNER).toBeGreaterThanOrEqual(2);
    expect(nextWakeupDecision(0, false)).toEqual({
      failures: 1,
      showBanner: false,
      nextDelayMs: RETRY_INTERVAL_MS,
    });
    expect(nextWakeupDecision(1, false).showBanner).toBe(true);
  });

  it("a success resets the count, hides the banner and goes back to keep-alive", () => {
    expect(nextWakeupDecision(5, true)).toEqual({
      failures: 0,
      showBanner: false,
      nextDelayMs: KEEP_ALIVE_INTERVAL_MS,
    });
  });
});

describe("ServerWakeupProvider (F-03)", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", fetchMock);
    fetchMock.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  async function flush() {
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
  }

  it("never blocks the page and shows the banner only after repeated failures", async () => {
    fetchMock.mockRejectedValue(new TypeError("fetch failed"));
    render(
      <ServerWakeupProvider>
        <input aria-label="half-filled form" defaultValue="keep me" />
      </ServerWakeupProvider>,
    );

    await flush();
    expect(screen.getByLabelText("half-filled form")).toBeInTheDocument();
    expect(screen.queryByTestId("server-wakeup.banner")).not.toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(RETRY_INTERVAL_MS);
    });
    const banner = screen.getByTestId("server-wakeup.banner");
    expect(banner).toHaveTextContent("Connecting to the server");
    expect(banner).not.toHaveTextContent(/free tier/i);
    expect(screen.getByLabelText("half-filled form")).toHaveValue("keep me");
  });

  it("hides the banner by itself once the backend answers again", async () => {
    fetchMock
      .mockRejectedValueOnce(new TypeError("fetch failed"))
      .mockRejectedValueOnce(new TypeError("fetch failed"))
      .mockResolvedValue({ ok: true });
    render(
      <ServerWakeupProvider>
        <p>app</p>
      </ServerWakeupProvider>,
    );
    await flush();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(RETRY_INTERVAL_MS);
    });
    expect(screen.getByTestId("server-wakeup.banner")).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(RETRY_INTERVAL_MS);
    });
    expect(screen.queryByTestId("server-wakeup.banner")).not.toBeInTheDocument();
    expect(screen.getByText("app")).toBeInTheDocument();
  });

  it("treats a check slower than the timeout as a failure", async () => {
    fetchMock.mockImplementation(
      (_url: string, init: { signal: AbortSignal }) =>
        new Promise((_resolve, reject) => {
          init.signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
        }),
    );
    render(
      <ServerWakeupProvider>
        <p>app</p>
      </ServerWakeupProvider>,
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(HEALTH_CHECK_TIMEOUT_MS - 1);
    });
    expect(screen.queryByTestId("server-wakeup.banner")).not.toBeInTheDocument();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1 + RETRY_INTERVAL_MS + HEALTH_CHECK_TIMEOUT_MS);
    });
    expect(screen.getByTestId("server-wakeup.banner")).toBeInTheDocument();
  });
});
