import { Tabs, TabsList, TabsTrigger, TabsContent } from "../ui/tabs";
import {
  FaDesktop,
  FaMobile,
  FaCode,
} from "react-icons/fa";
import {
  LuChevronLeft,
  LuChevronRight,
  LuExternalLink,
  LuRefreshCw,
  LuDownload,
} from "react-icons/lu";
import { useCallback, useMemo, useRef, useState } from "react";
import { nanoid } from "nanoid";
import toast from "react-hot-toast";
import { AppState, Settings } from "../../types";
import CodeTab from "./CodeTab";
import { Button } from "../ui/button";
import { useAppStore } from "../../store/app-store";
import { useProjectStore } from "../../store/project-store";
import { extractHtml } from "./extractHtml";
import PreviewComponent from "./PreviewComponent";
import { downloadCode } from "./download";
import { SelectAndEditToolbarButton } from "../select-and-edit/SelectAndEditControls";
import { normalizeBabelCdn } from "../../lib/babelCdn";
import ImageScanningPreview from "./ImageScanningPreview";
import { useDebouncedCallback } from "../../hooks/useDebouncedCallback";
import { saveVersion } from "../../lib/runs";
import { Popover, PopoverContent, PopoverTrigger } from "../ui/popover";
import BuildAppPanel from "../build/BuildAppPanel";

// Manual edits are saved to the backend run after this much idle time.
const MANUAL_EDIT_SAVE_DELAY_MS = 1500;

interface ManualEditSave {
  runId: string;
  hash: string;
  parentCommitHash: string | null;
  optionIndex: number;
}

function prepareHtmlForNewTab(code: string) {
  const html = normalizeBabelCdn(code);
  if (/<base\s/i.test(html)) return html;

  const baseTag = `<base href="${window.location.origin}/">`;
  return html.replace(/<head(\s[^>]*)?>/i, (match) => `${match}${baseTag}`);
}

function openInNewTab(code: string) {
  const blob = new Blob([prepareHtmlForNewTab(code)], { type: "text/html" });
  const url = URL.createObjectURL(blob);
  window.open(url, "_blank");
  window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

interface Props {
  settings: Settings;
  onOpenVersions: () => void;
}

function PreviewPane({ settings, onOpenVersions }: Props) {
  const { appState } = useAppStore();
  const { inputMode, head, commits, setHead, runId } = useProjectStore();
  const [activeTab, setActiveTab] = useState("desktop");
  const [desktopScale, setDesktopScale] = useState(1);
  const [desktopViewMode, setDesktopViewMode] = useState<"fit" | "actual">("fit");

  // Sorted commit list for version navigation
  const sortedCommits = useMemo(() =>
    Object.values(commits).sort(
      (a, b) => new Date(a.dateCreated).getTime() - new Date(b.dateCreated).getTime()
    ), [commits]);

  const currentVersionIndex = sortedCommits.findIndex(c => c.hash === head);
  const totalVersions = sortedCommits.length;
  const canGoPrev = currentVersionIndex > 0;
  const canGoNext = currentVersionIndex < totalVersions - 1;

  const currentCommit = head && commits[head] ? commits[head] : "";
  const currentCode = currentCommit
    ? currentCommit.variants[currentCommit.selectedVariantIndex].code
    : "";

  const isSelectedVariantComplete =
    head &&
    commits[head] &&
    commits[head].variants[commits[head].selectedVariantIndex].status ===
      "complete";

  const previewCode =
    inputMode === "video" && appState === AppState.CODING
      ? extractHtml(currentCode)
      : currentCode;
  const sourceImage = currentCommit ? currentCommit.inputs?.images[0] : undefined;
  const showImageScanningPreview =
    appState === AppState.CODING &&
    currentCommit !== "" &&
    currentCommit.type === "ai_create" &&
    inputMode === "image" &&
    !previewCode.trim() &&
    !!sourceImage;

  const canSelectAndEdit =
    appState === AppState.CODE_READY || !!isSelectedVariantComplete;

  const headGitSha = currentCommit ? currentCommit.gitSha : undefined;
  const canBuildApp = canSelectAndEdit && !!runId && !!headGitSha;

  // Saves run one after another so a version's git commits land in order.
  const saveChainRef = useRef<Promise<void>>(Promise.resolve());
  const saveManualEdit = useCallback((job: ManualEditSave) => {
    saveChainRef.current = saveChainRef.current.then(async () => {
      const commit = useProjectStore.getState().commits[job.hash];
      if (!commit) return;
      try {
        const { gitSha, visualQa } = await saveVersion(job.runId, job.hash, {
          parentCommitHash: job.parentCommitHash,
          optionIndex: job.optionIndex,
          code: commit.variants[0]?.code ?? "",
        });
        const project = useProjectStore.getState();
        project.setCommitGitSha(job.hash, gitSha);
        // Same store action as the websocket `visualQa` message.
        if (visualQa) project.setCommitVisualQa(job.hash, visualQa);
      } catch (error) {
        console.error("Failed to save manual edit", error);
        const reason = error instanceof Error ? error.message : String(error);
        toast.error(`Could not save manual edit: ${reason}`, {
          id: "manual-edit-save",
        });
      }
    });
  }, []);
  const debouncedSave = useDebouncedCallback(
    saveManualEdit,
    MANUAL_EDIT_SAVE_DELAY_MS
  );
  const pendingSaveHashRef = useRef<string | null>(null);

  // CodeMirror captures this callback once, so it reads everything from the
  // stores instead of closing over render-time state.
  const handleCodeChange = useCallback(
    (code: string) => {
      if (useAppStore.getState().appState !== AppState.CODE_READY) return;
      const project = useProjectStore.getState();
      const headCommit = project.head ? project.commits[project.head] : null;
      if (!headCommit) return;
      // The editor also reports programmatic syncs (version switches,
      // streaming); only a real difference is a manual edit.
      const headCode =
        headCommit.variants[headCommit.selectedVariantIndex]?.code ?? "";
      if (code === headCode) return;

      const hash = project.applyManualEdit(code, nanoid());
      const commit = hash ? useProjectStore.getState().commits[hash] : null;
      if (!hash || !commit || commit.type !== "code_edit") return;
      const runId = useProjectStore.getState().runId;
      if (!runId) return; // e.g. imported code: no backend run to save into

      // Never let a pending save of another version be replaced.
      if (pendingSaveHashRef.current && pendingSaveHashRef.current !== hash) {
        debouncedSave.flush();
      }
      pendingSaveHashRef.current = hash;
      debouncedSave.call({
        runId,
        hash,
        parentCommitHash: commit.parentHash,
        optionIndex: commit.optionIndex,
      });
    },
    [debouncedSave]
  );

  return (
    <div className="flex-1 flex flex-col min-h-0">
      <Tabs
        value={activeTab}
        onValueChange={setActiveTab}
        className="flex-1 flex flex-col min-h-0"
      >
        <div className="relative flex items-center justify-between px-4 py-2 shrink-0 border-b border-gray-200 dark:border-zinc-800 bg-white dark:bg-zinc-950">
          <div className="flex items-center gap-2">
            <TabsList>
              <TabsTrigger value="desktop" title="Desktop" data-testid="tab-desktop">
                <FaDesktop />
              </TabsTrigger>
              <TabsTrigger value="mobile" title="Mobile" data-testid="tab-mobile">
                <FaMobile />
              </TabsTrigger>
              <TabsTrigger value="code" title="Code" data-testid="tab-code" className="gap-2">
                <FaCode />
                Code
              </TabsTrigger>
            </TabsList>
            {(activeTab === "desktop" || activeTab === "mobile") && (
              <div className="hidden sm:inline-flex items-center gap-2">
                {activeTab === "desktop" && (
                  <div className="inline-flex items-center rounded-lg bg-gray-100 p-1 dark:bg-zinc-800">
                    <button
                      type="button"
                      onClick={() => setDesktopViewMode("fit")}
                      title="Scale down to fit the screen"
                      className={`rounded-md px-3 py-1.5 text-xs font-medium transition-all ${
                        desktopViewMode === "fit"
                          ? "bg-white text-gray-900 shadow-sm dark:bg-zinc-600 dark:text-zinc-100"
                          : "text-gray-500 hover:text-gray-900 dark:text-zinc-400 dark:hover:text-zinc-200"
                      }`}
                    >
                      Scale
                      {desktopScale < 1 && (
                        <span className="ml-1 text-violet-600 dark:text-violet-300 font-bold">
                          ({Math.round(desktopScale * 100)}%)
                        </span>
                      )}
                    </button>
                    <button
                      type="button"
                      onClick={() => setDesktopViewMode("actual")}
                      title="View at original size (100%)"
                      className={`rounded-md px-3 py-1.5 text-xs font-medium transition-all ${
                        desktopViewMode === "actual"
                          ? "bg-white text-gray-900 shadow-sm dark:bg-zinc-600 dark:text-zinc-100"
                          : "text-gray-500 hover:text-gray-900 dark:text-zinc-400 dark:hover:text-zinc-200"
                      }`}
                    >
                      100%
                    </button>
                  </div>
                )}
                <Button
                  onClick={() => openInNewTab(previewCode)}
                  variant="ghost"
                  size="icon"
                  title="Open in New Tab"
                  className="h-8 w-8"
                >
                  <LuExternalLink />
                </Button>
              </div>
            )}
          </div>

          {/* Version navigation */}
          {totalVersions > 0 && (
            <div className="hidden md:flex shrink-0 items-center justify-center gap-1 bg-gray-100/50 dark:bg-zinc-800/50 rounded-full p-1 border border-gray-200/50 dark:border-zinc-700/50 backdrop-blur-sm">
              <Button
                onClick={() => canGoPrev && setHead(sortedCommits[currentVersionIndex - 1].hash)}
                variant="ghost"
                size="icon"
                title="Previous version"
                className={`h-6 w-6 rounded-full hover:bg-white dark:hover:bg-zinc-700 ${!canGoPrev ? "opacity-30 cursor-not-allowed" : ""}`}
                disabled={!canGoPrev}
              >
                <LuChevronLeft className="w-3.5 h-3.5" />
              </Button>
              <div
                onClick={onOpenVersions}
                className="flex items-center justify-center gap-2 px-1 cursor-pointer hover:opacity-70 transition-opacity w-32"
                title="View all versions"
              >
                <span className="text-xs font-semibold text-gray-700 dark:text-gray-200 leading-none">
                  Version {currentVersionIndex + 1}
                </span>
                {currentVersionIndex === totalVersions - 1 && (
                  <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[10px] font-medium text-gray-700 dark:bg-gray-800 dark:text-gray-300 leading-none flex items-center h-4">
                    Latest
                  </span>
                )}
              </div>
              <Button
                onClick={() => canGoNext && setHead(sortedCommits[currentVersionIndex + 1].hash)}
                variant="ghost"
                size="icon"
                title="Next version"
                className={`h-6 w-6 rounded-full hover:bg-white dark:hover:bg-zinc-700 ${!canGoNext ? "opacity-30 cursor-not-allowed" : ""}`}
                disabled={!canGoNext}
              >
                <LuChevronRight className="w-3.5 h-3.5" />
              </Button>
            </div>
          )}

          <div className="flex items-center gap-1">
            {canSelectAndEdit &&
              (activeTab === "desktop" || activeTab === "mobile") && (
                <SelectAndEditToolbarButton />
              )}
            {canSelectAndEdit && (
              <Popover>
                <PopoverTrigger asChild>
                  <button
                    type="button"
                    disabled={!canBuildApp}
                    data-testid="build-app"
                    title={
                      canBuildApp
                        ? "Build this version into a running app"
                        : "Available once this version is saved to the run (git SHA shown in Versions)"
                    }
                    className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-xs font-medium text-gray-600 transition-colors hover:border-violet-300 hover:text-violet-700 disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:border-gray-200 disabled:hover:text-gray-600 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:border-violet-500 dark:hover:text-violet-300"
                  >
                    🚀 Build app
                  </button>
                </PopoverTrigger>
                {canBuildApp && head && runId && (
                  <PopoverContent align="end" className="w-80">
                    <BuildAppPanel
                      runId={runId}
                      commitHash={head}
                      versionNumber={currentVersionIndex + 1}
                      settings={settings}
                    />
                  </PopoverContent>
                )}
              </Popover>
            )}
            {(appState === AppState.CODE_READY || isSelectedVariantComplete) && (
              <Button
                onClick={() => downloadCode(previewCode)}
                variant="ghost"
                size="icon"
                title="Download Code"
                className="h-9 w-9"
                data-testid="download-code"
              >
                <LuDownload />
              </Button>
            )}
            <Button
              onClick={() => {
                const iframes = document.querySelectorAll("iframe");
                iframes.forEach((iframe) => {
                  if (iframe.srcdoc) {
                    const content = iframe.srcdoc;
                    iframe.srcdoc = "";
                    iframe.srcdoc = content;
                  }
                });
              }}
              variant="ghost"
              size="icon"
              title="Refresh Preview"
              className="h-9 w-9"
            >
              <LuRefreshCw />
            </Button>
          </div>
        </div>
        <TabsContent value="desktop" className="flex-1 min-h-0 mt-0 data-[state=active]:flex data-[state=active]:flex-col">
          {showImageScanningPreview ? (
            <ImageScanningPreview imageUrl={sourceImage} />
          ) : (
            <PreviewComponent
              code={previewCode}
              device="desktop"
              onScaleChange={setDesktopScale}
              viewMode={desktopViewMode}
            />
          )}
        </TabsContent>
        <TabsContent value="mobile" className="flex-1 min-h-0 mt-0 data-[state=active]:flex data-[state=active]:flex-col">
          {showImageScanningPreview ? (
            <ImageScanningPreview imageUrl={sourceImage} />
          ) : (
            <PreviewComponent
              code={previewCode}
              device="mobile"
              viewMode="actual"
            />
          )}
        </TabsContent>
        <TabsContent value="code" className="flex-1 min-h-0 mt-0 overflow-auto">
          <CodeTab
            code={previewCode}
            setCode={handleCodeChange}
            settings={settings}
          />
        </TabsContent>
      </Tabs>
    </div>
  );
}

export default PreviewPane;
