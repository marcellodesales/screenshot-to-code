import { useEffect, useMemo, useRef } from "react";
import { createDebouncer, Debouncer } from "../lib/debounce";

// Stable trailing-edge debounced callback that always calls the latest `fn`.
// A pending call is flushed (not dropped) when the component unmounts.
export function useDebouncedCallback<Args extends unknown[]>(
  fn: (...args: Args) => void,
  delayMs: number
): Debouncer<Args> {
  const fnRef = useRef(fn);
  useEffect(() => {
    fnRef.current = fn;
  }, [fn]);

  const debouncer = useMemo(
    () => createDebouncer<Args>((...args) => fnRef.current(...args), delayMs),
    [delayMs]
  );

  useEffect(() => () => debouncer.flush(), [debouncer]);

  return debouncer;
}
