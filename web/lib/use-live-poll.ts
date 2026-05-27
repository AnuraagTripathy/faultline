import { useEffect, useRef } from "react";

/** Poll interval while a run is active (matches legacy cloud dashboard). */
export const LIVE_POLL_MS = 2000;

/**
 * Calls `callback` on a fixed interval while `enabled` is true.
 * Uses a ref so the latest callback runs without resetting the timer.
 */
export function useLivePoll(
  callback: () => void | Promise<void>,
  enabled: boolean,
  intervalMs: number = LIVE_POLL_MS
): void {
  const callbackRef = useRef(callback);
  callbackRef.current = callback;

  useEffect(() => {
    if (!enabled) return;
    const tick = () => {
      void callbackRef.current();
    };
    const id = setInterval(tick, intervalMs);
    return () => clearInterval(id);
  }, [enabled, intervalMs]);
}

export function hasRunningRun(runs: { status: string }[]): boolean {
  return runs.some((r) => r.status === "running");
}
