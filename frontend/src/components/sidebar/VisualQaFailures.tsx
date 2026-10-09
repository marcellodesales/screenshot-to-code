import { VisualQaData, qaFailures } from "../../lib/visualQa";

interface Props {
  visualQa: VisualQaData | undefined;
}

// Chat-row note for a version whose options failed a visual QA check
// (blank render, duplicate, not responsive): the 1280 px QA screenshot of
// each failing option, opening the full-size PNG in a new tab. Passing
// options add nothing.
function VisualQaFailures({ visualQa }: Props) {
  const failures = qaFailures(visualQa);
  if (failures.length === 0) return null;

  return (
    <div
      className="mb-3 rounded-xl border border-amber-200 bg-amber-50/60 px-3 py-2 dark:border-amber-800/60 dark:bg-amber-900/10"
      data-testid="visual-qa-failures"
    >
      <p className="mb-2 text-xs font-medium text-amber-900 dark:text-amber-200">
        Visual QA flagged {failures.length === 1 ? "an option" : `${failures.length} options`}
      </p>
      <div className="flex flex-wrap gap-2">
        {failures.map((failure) => {
          const caption = `Option ${failure.index + 1}: ${failure.labels.join(", ")}`;
          return (
            <figure key={failure.index} className="w-36 shrink-0">
              {failure.screenshotUrl ? (
                <a
                  href={failure.screenshotUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  title={`${caption} — open full size`}
                  className="block overflow-hidden rounded-md border border-gray-200 bg-white hover:border-violet-400 dark:border-zinc-700 dark:bg-zinc-900 dark:hover:border-violet-500"
                >
                  <img
                    src={failure.screenshotUrl}
                    alt={caption}
                    className="h-20 w-full object-cover object-top"
                    loading="lazy"
                  />
                </a>
              ) : (
                <div className="flex h-20 items-center justify-center rounded-md border border-dashed border-gray-300 text-[10px] text-gray-400 dark:border-zinc-700">
                  No screenshot
                </div>
              )}
              <figcaption className="mt-1 text-[11px] leading-tight text-gray-700 dark:text-zinc-300">
                <span className="font-medium">Option {failure.index + 1}</span>
                {failure.labels.map((label) => (
                  <span key={label} className="block text-amber-800 dark:text-amber-300">
                    {label}
                  </span>
                ))}
              </figcaption>
            </figure>
          );
        })}
      </div>
    </div>
  );
}

export default VisualQaFailures;
