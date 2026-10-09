import { createDebouncer } from "./debounce";

describe("createDebouncer", () => {
  beforeEach(() => jest.useFakeTimers());
  afterEach(() => jest.useRealTimers());

  it("runs only the last call after the idle delay", () => {
    const fn = jest.fn();
    const debounced = createDebouncer(fn, 1500);

    debounced.call("a");
    jest.advanceTimersByTime(1000);
    debounced.call("b");
    jest.advanceTimersByTime(1499);
    expect(fn).not.toHaveBeenCalled();

    jest.advanceTimersByTime(1);
    expect(fn).toHaveBeenCalledTimes(1);
    expect(fn).toHaveBeenCalledWith("b");
  });

  it("cancel drops the pending call", () => {
    const fn = jest.fn();
    const debounced = createDebouncer(fn, 1500);

    debounced.call("a");
    debounced.cancel();
    jest.advanceTimersByTime(5000);
    expect(fn).not.toHaveBeenCalled();
  });

  it("flush runs the pending call immediately", () => {
    const fn = jest.fn();
    const debounced = createDebouncer(fn, 1500);

    debounced.call("a");
    debounced.flush();
    expect(fn).toHaveBeenCalledWith("a");
    jest.advanceTimersByTime(5000);
    expect(fn).toHaveBeenCalledTimes(1);
  });
});
