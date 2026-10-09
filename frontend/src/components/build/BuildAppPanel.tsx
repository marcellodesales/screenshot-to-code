import { useCallback, useEffect, useMemo, useState } from "react";
import { BsExclamationTriangleFill } from "react-icons/bs";
import { LuExternalLink } from "react-icons/lu";
import { Settings } from "../../types";
import { Button } from "../ui/button";
import {
  BuildJob,
  buildStartBody,
  distinctOptionIndices,
  getBuild,
  isBuildFinished,
  OptionState,
  OptionStatus,
  parityLabel,
  RunsApiError,
  startBuild,
} from "../../lib/runs";
import { qaAssetUrl, qaForOption } from "../../lib/visualQa";
import { useProjectStore } from "../../store/project-store";
import { buildOptionsFor } from "./buildOptions";

const POLL_INTERVAL_MS = 2000;

const STATE_LABELS: Record<OptionState, string> = {
  queued: "Queued",
  scaffolding: "Scaffolding",
  migrating: "Migrating",
  building: "Building",
  committing: "Committing",
  starting: "Starting",
  running: "Running",
  failed: "Failed",
};

function stateDotClass(state: OptionState) {
  if (state === "running") return "bg-emerald-500";
  if (state === "failed") return "bg-red-500";
  return "bg-amber-400 animate-pulse";
}

interface Props {
  runId: string;
  commitHash: string;
  versionNumber: number;
  settings: Settings;
}

function OptionRow({ option }: { option: OptionStatus }) {
  return (
    <li className="rounded-md border border-gray-100 px-3 py-2 dark:border-zinc-700">
      <div className="flex items-center gap-2">
        <span
          className={`h-2 w-2 shrink-0 rounded-full ${stateDotClass(option.state)}`}
        />
        <span className="text-xs font-medium text-gray-800 dark:text-zinc-200">
          Option {option.index + 1}
        </span>
        <span className="ml-auto text-[10px] uppercase tracking-wider text-gray-500 dark:text-zinc-400">
          {STATE_LABELS[option.state] ?? option.state}
        </span>
      </div>
      {option.stepMessage && option.state !== "running" && (
        <p className="mt-1 text-xs text-gray-500 dark:text-zinc-400">
          {option.stepMessage}
        </p>
      )}
      {option.url && (
        <a
          href={option.url}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-1 flex items-center gap-1 break-all font-mono text-xs text-violet-600 hover:text-violet-700 dark:text-violet-400 dark:hover:text-violet-300"
        >
          {option.url}
          <LuExternalLink className="h-3 w-3 shrink-0" />
        </a>
      )}
      {option.error && (
        <p className="mt-1 break-words text-xs text-red-600 dark:text-red-400">
          {option.error}
        </p>
      )}
      <OptionQa option={option} />
    </li>
  );
}

// App screenshot + parity / responsive / render checks of a running option.
function OptionQa({ option }: { option: OptionStatus }) {
  const screenshotUrl = qaAssetUrl(option.screenshot);
  const parity = option.parity !== null ? parityLabel(option.parity) : null;
  const hasChecks =
    screenshotUrl !== null ||
    parity !== null ||
    option.responsive !== null ||
    option.renderOk === false;
  if (!hasChecks) return null;

  return (
    <div className="mt-2 flex items-start gap-2" data-testid="build-option-qa">
      {screenshotUrl && (
        <a
          href={screenshotUrl}
          target="_blank"
          rel="noopener noreferrer"
          title="Open the app screenshot full size"
          className="block w-24 shrink-0 overflow-hidden rounded border border-gray-200 hover:border-violet-400 dark:border-zinc-700 dark:hover:border-violet-500"
        >
          <img
            src={screenshotUrl}
            alt={`Option ${option.index + 1} app screenshot`}
            className="h-14 w-full object-cover object-top"
            loading="lazy"
          />
        </a>
      )}
      <div className="flex flex-wrap gap-1">
        {parity && (
          <span
            className={`rounded px-1.5 py-0.5 text-[10px] font-medium leading-none ${
              parity.isLow
                ? "bg-amber-50 text-amber-800 dark:bg-amber-900/30 dark:text-amber-200"
                : "bg-emerald-50 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300"
            }`}
          >
            {parity.text}
          </span>
        )}
        {option.responsive && (
          <span
            className={`rounded px-1.5 py-0.5 text-[10px] font-medium leading-none ${
              option.responsive.pass
                ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300"
                : "bg-amber-50 text-amber-800 dark:bg-amber-900/30 dark:text-amber-200"
            }`}
          >
            {option.responsive.pass ? "responsive" : "⚠ not responsive"}
          </span>
        )}
        {option.renderOk === false && (
          <span className="rounded bg-red-50 px-1.5 py-0.5 text-[10px] font-medium leading-none text-red-700 dark:bg-red-900/30 dark:text-red-300">
            ⚠ blank or broken render
          </span>
        )}
      </div>
    </div>
  );
}

function sameIndexes(a: number[], b: number[]) {
  return a.length === b.length && a.every((value, i) => value === b[i]);
}

// "🚀 Build app" panel: starts a build of the selected version and polls its
// per-option progress until every option is running or failed (spec §7, §8).
function BuildAppPanel({ runId, commitHash, versionNumber, settings }: Props) {
  const [job, setJob] = useState<BuildJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isDisabledOnBackend, setIsDisabledOnBackend] = useState(false);
  const [isStarting, setIsStarting] = useState(false);
  const [isPolling, setIsPolling] = useState(false);

  // Which options to build: the selected option by default, or every option
  // visual QA didn't mark as a duplicate.
  const commits = useProjectStore((state) => state.commits);
  const { optionCount, selectedIndex, visualQa } = buildOptionsFor(
    commits,
    commitHash
  );
  const distinct = useMemo(
    () => distinctOptionIndices(optionCount, visualQa),
    [optionCount, visualQa]
  );
  const [chosen, setChosen] = useState<number[]>([selectedIndex]);
  useEffect(() => {
    setChosen([selectedIndex]);
  }, [commitHash, selectedIndex]);
  const isAllDistinct = sameIndexes(chosen, distinct);

  const toggleOption = (index: number) => {
    setChosen((current) =>
      current.includes(index)
        ? current.filter((value) => value !== index)
        : [...current, index].sort((a, b) => a - b)
    );
  };

  const reportError = useCallback((err: unknown) => {
    if (err instanceof RunsApiError && err.status === 403) {
      setIsDisabledOnBackend(true);
    }
    setError(err instanceof Error ? err.message : String(err));
  }, []);

  // Show an existing (possibly still running) build of this run on open.
  useEffect(() => {
    let cancelled = false;
    getBuild(runId)
      .then((existing) => {
        if (cancelled || !existing) return;
        setJob(existing);
        if (!isBuildFinished(existing)) setIsPolling(true);
      })
      .catch(() => {
        /* no build yet / backend without build routes: nothing to show */
      });
    return () => {
      cancelled = true;
    };
  }, [runId]);

  useEffect(() => {
    if (!isPolling) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const poll = async () => {
      try {
        const latest = await getBuild(runId);
        if (cancelled) return;
        if (latest) setJob(latest);
        if (!latest || isBuildFinished(latest)) {
          setIsPolling(false);
          return;
        }
      } catch (err) {
        if (cancelled) return;
        reportError(err);
        setIsPolling(false);
        return;
      }
      timer = setTimeout(poll, POLL_INTERVAL_MS);
    };

    timer = setTimeout(poll, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [isPolling, runId, reportError]);

  const handleStart = async () => {
    setError(null);
    setIsDisabledOnBackend(false);
    setIsStarting(true);
    try {
      const started = await startBuild(
        runId,
        buildStartBody(commitHash, settings, chosen)
      );
      setJob(started);
      setIsPolling(!isBuildFinished(started));
    } catch (err) {
      reportError(err);
    } finally {
      setIsStarting(false);
    }
  };

  const isInProgress = isPolling || (job !== null && !isBuildFinished(job));
  const isOtherVersion = job !== null && job.uiCommitHash !== commitHash;

  return (
    <div className="flex flex-col gap-3" data-testid="build-app-panel">
      <div>
        <h3 className="text-sm font-medium text-gray-900 dark:text-white">
          Build app
        </h3>
        <p className="mt-0.5 text-xs text-gray-500 dark:text-zinc-400">
          Turn the chosen options of Version {versionNumber} into running
          apps with <span className="font-mono">{settings.buildSystem}</span>.
        </p>
      </div>

      {optionCount > 1 && (
        <fieldset
          className="flex flex-col gap-1.5"
          data-testid="build-option-picker"
          disabled={isStarting || isInProgress}
        >
          <ul className="flex flex-wrap gap-x-3 gap-y-1">
            {Array.from({ length: optionCount }, (_, index) => {
              const qa = qaForOption(visualQa, index);
              const duplicateOf = qa?.duplicateOf ?? null;
              return (
                <li key={index}>
                  <label className="flex items-center gap-1.5 text-xs text-gray-700 dark:text-zinc-300">
                    <input
                      type="checkbox"
                      className="accent-violet-600"
                      checked={chosen.includes(index)}
                      onChange={() => toggleOption(index)}
                    />
                    Option {index + 1}
                    {index === selectedIndex && (
                      <span className="text-[10px] text-gray-400 dark:text-zinc-500">
                        (selected)
                      </span>
                    )}
                    {duplicateOf !== null && (
                      <span className="text-[10px] text-gray-400 dark:text-zinc-500">
                        ≈ Option {duplicateOf + 1}
                      </span>
                    )}
                  </label>
                </li>
              );
            })}
          </ul>
          <label className="flex items-center gap-1.5 text-xs font-medium text-gray-700 dark:text-zinc-300">
            <input
              type="checkbox"
              className="accent-violet-600"
              checked={isAllDistinct}
              onChange={(event) =>
                setChosen(event.target.checked ? distinct : [selectedIndex])
              }
              data-testid="build-all-distinct"
            />
            Build all distinct options
            {distinct.length < optionCount && (
              <span className="font-normal text-gray-400 dark:text-zinc-500">
                ({optionCount - distinct.length} duplicate
                {optionCount - distinct.length === 1 ? "" : "s"} skipped)
              </span>
            )}
          </label>
        </fieldset>
      )}

      {isDisabledOnBackend ? (
        <div className="flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 p-2.5 dark:border-amber-700/60 dark:bg-amber-900/20">
          <BsExclamationTriangleFill className="mt-0.5 shrink-0 text-amber-500" />
          <p className="text-xs text-amber-800 dark:text-amber-200">{error}</p>
        </div>
      ) : (
        error && (
          <p className="break-words rounded-md border border-red-200 bg-red-50 p-2.5 text-xs text-red-700 dark:border-red-800/60 dark:bg-red-900/20 dark:text-red-300">
            {error}
          </p>
        )
      )}

      {job && (
        <div className="flex flex-col gap-1.5">
          {isOtherVersion && (
            <p className="text-xs text-gray-500 dark:text-zinc-400">
              Last build of this project (another version):
            </p>
          )}
          <ul className="flex flex-col gap-1.5">
            {job.options.map((option) => (
              <OptionRow key={option.index} option={option} />
            ))}
          </ul>
        </div>
      )}

      <Button
        size="sm"
        onClick={handleStart}
        disabled={isStarting || isInProgress || chosen.length === 0}
        data-testid="build-app-start"
      >
        {isStarting
          ? "Starting…"
          : isInProgress
            ? "Building…"
            : job && !isOtherVersion
              ? "Rebuild"
              : `Build Version ${versionNumber}`}
      </Button>
    </div>
  );
}

export default BuildAppPanel;
