import { useEffect, useRef } from "react";

type PollCallback = () => void | Promise<void>;

export function usePolling(callback: PollCallback, intervalMs: number, enabled: boolean) {
  const saved = useRef(callback);
  useEffect(() => {
    saved.current = callback;
  }, [callback]);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const schedule = () => {
      if (!cancelled) timer = setTimeout(run, intervalMs);
    };

    const run = () => {
      let pending: void | Promise<void>;
      try {
        pending = saved.current();
      } catch {
        schedule();
        return;
      }
      void Promise.resolve(pending)
        .catch(() => undefined)
        .finally(schedule);
    };

    schedule();
    return () => {
      cancelled = true;
      if (timer !== undefined) clearTimeout(timer);
    };
  }, [enabled, intervalMs]);
}
