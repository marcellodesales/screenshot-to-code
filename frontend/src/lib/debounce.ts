export interface Debouncer<Args extends unknown[]> {
  call: (...args: Args) => void;
  cancel: () => void;
  flush: () => void;
}

// Trailing-edge debounce: `fn` runs with the latest arguments once `delayMs`
// have passed without another call.
export function createDebouncer<Args extends unknown[]>(
  fn: (...args: Args) => void,
  delayMs: number
): Debouncer<Args> {
  let timer: ReturnType<typeof setTimeout> | null = null;
  let pendingArgs: Args | null = null;

  const run = () => {
    timer = null;
    const args = pendingArgs;
    pendingArgs = null;
    if (args) fn(...args);
  };

  return {
    call: (...args: Args) => {
      pendingArgs = args;
      if (timer !== null) clearTimeout(timer);
      timer = setTimeout(run, delayMs);
    },
    cancel: () => {
      if (timer !== null) clearTimeout(timer);
      timer = null;
      pendingArgs = null;
    },
    flush: () => {
      if (timer !== null) clearTimeout(timer);
      run();
    },
  };
}
