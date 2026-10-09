import { useCallback, useEffect, useState } from "react";
import { BsExclamationTriangleFill } from "react-icons/bs";
import { LuExternalLink } from "react-icons/lu";
import { Settings } from "../../types";
import { Button } from "../ui/button";
import {
  BuildJob,
  buildStartBody,
  getBuild,
  isBuildFinished,
  OptionState,
  OptionStatus,
  RunsApiError,
  startBuild,
} from "../../lib/runs";

const POLL_INTERVAL_MS = 2000;

const STATE_LABELS: Record<OptionState, string> = {
  queued: "Queued",
  scaffolding: "Scaffolding",
  migrating: "Migrating",
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
    </li>
  );
}

// "🚀 Build app" panel: starts a build of the selected version and polls its
// per-option progress until every option is running or failed (spec §7, §8).
function BuildAppPanel({ runId, commitHash, versionNumber, settings }: Props) {
  const [job, setJob] = useState<BuildJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isDisabledOnBackend, setIsDisabledOnBackend] = useState(false);
  const [isStarting, setIsStarting] = useState(false);
  const [isPolling, setIsPolling] = useState(false);

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
        buildStartBody(commitHash, settings)
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
          Turn every option of Version {versionNumber} into a running app with{" "}
          <span className="font-mono">{settings.buildSystem}</span>.
        </p>
      </div>

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
        disabled={isStarting || isInProgress}
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
