"use client";

// Migrated from `function Counter()` in design/mock.html. Uses state, so it
// is a Client Component; `React.useState` global -> named import.
import { useState } from "react";

export default function Counter() {
  const [count, setCount] = useState(0);
  return (
    <button
      type="button"
      className="rounded-lg bg-indigo-600 px-4 py-2 font-semibold text-white hover:bg-indigo-500"
      onClick={() => setCount(count + 1)}
    >
      Clicked {count} times
    </button>
  );
}
