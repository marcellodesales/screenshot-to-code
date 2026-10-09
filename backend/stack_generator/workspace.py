"""Per-run workspace: one git repo per run under ``RUNS_DIR/<run-id>/``.

Layout (spec §2, §2.1):

    stack.yaml                 run metadata + versions index
    uploads/{video,screenshots}/  original uploads (gitignored)
    op<N>/design/mock.html     option N of the selected version (1-based)
    op<N>/app/                 generated app ("Build app")

Every UI version is a commit written with ``git commit-tree`` whose parent is
the commit of its UI parent version, so forks in the UI history are forks in
git. Each version is pinned by ``refs/s2c/versions/<ui-commit-hash>``; ``main``
points at the most recent version or build. Trees are built in a throwaway
index from the base commit, so the working tree never leaks into a commit.
"""

import base64
import binascii
import mimetypes
import os
import re
import shutil
import subprocess
import tempfile
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, cast

import yaml

import config

RUN_ID_PATTERN = re.compile(r"^run_\d{8}_\d{6}_[0-9a-f]{8}$")
# UI commit hashes are nanoids; anything else must never reach a ref name.
_UI_COMMIT_HASH_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_MOCK_PATH_PATTERN = re.compile(r"^op(\d+)/design/mock\.html$")
_DATA_URL_PATTERN = re.compile(r"^data:([\w.+-]+/[\w.+-]+)?(?:;[^,]*)?;base64,(.*)$", re.S)

_GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "screenshot-to-code",
    "GIT_AUTHOR_EMAIL": "noreply@screenshot-to-code.local",
    "GIT_COMMITTER_NAME": "screenshot-to-code",
    "GIT_COMMITTER_EMAIL": "noreply@screenshot-to-code.local",
}
_GITIGNORE = "uploads/\n"
_VERSION_REF_PREFIX = "refs/s2c/versions/"

# Serialises git/stack.yaml mutations per run (websocket + HTTP edits).
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(path: Path) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(str(path), threading.Lock())


def new_run_id() -> str:
    return f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"


def default_runs_dir() -> Path:
    # Read at call time so tests (and late env changes) take effect.
    return Path(os.environ.get("RUNS_DIR", config.RUNS_DIR))


def run_dir_for(run_id: str, runs_dir: Path | None = None) -> Path | None:
    """Run directory for a well-formed run id; ``None`` for anything else."""
    if not isinstance(run_id, str) or not RUN_ID_PATTERN.match(run_id):
        return None
    return (runs_dir if runs_dir is not None else default_runs_dir()) / run_id


def _check_ui_commit_hash(ui_commit_hash: str) -> str:
    if not _UI_COMMIT_HASH_PATTERN.match(ui_commit_hash):
        raise ValueError(f"Invalid UI commit hash: {ui_commit_hash!r}")
    return ui_commit_hash


def _mock_path(option_number: int) -> str:
    return f"op{option_number}/design/mock.html"


class RunWorkspace:
    def __init__(self, run_id: str, path: Path) -> None:
        self.run_id = run_id
        self.path = path

    # -- lifecycle -------------------------------------------------------

    @classmethod
    def create(
        cls,
        run_id: str,
        *,
        source_stack: str,
        input_mode: str,
        prompt_text: str,
        runs_dir: Path | None = None,
    ) -> "RunWorkspace":
        path = run_dir_for(run_id, runs_dir)
        if path is None:
            raise ValueError(f"Invalid run id: {run_id!r}")
        path.mkdir(parents=True, exist_ok=False)
        (path / "uploads" / "video").mkdir(parents=True)
        (path / "uploads" / "screenshots").mkdir(parents=True)
        (path / ".gitignore").write_text(_GITIGNORE, encoding="utf-8")
        workspace = cls(run_id, path)
        workspace._write_metadata(
            {
                "run_id": run_id,
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "source_stack": source_stack,
                "input_mode": input_mode,
                "prompt": prompt_text,
                "versions": [],
            }
        )
        workspace._git("init", "-q", "-b", "main")
        return workspace

    @classmethod
    def open(cls, run_id: str, runs_dir: Path | None = None) -> "RunWorkspace | None":
        path = run_dir_for(run_id, runs_dir)
        if path is None or not (path / ".git").is_dir():
            return None
        return cls(run_id, path)

    # -- metadata ----------------------------------------------------------

    @property
    def metadata(self) -> dict[str, Any]:
        """Parsed ``stack.yaml`` (run metadata and the versions index)."""
        data: Any = yaml.safe_load(
            (self.path / "stack.yaml").read_text(encoding="utf-8")
        )
        return cast(dict[str, Any], data) if isinstance(data, dict) else {}

    def _write_metadata(self, metadata: dict[str, Any]) -> None:
        (self.path / "stack.yaml").write_text(
            yaml.safe_dump(metadata, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )

    def _versions(self) -> list[dict[str, Any]]:
        versions: Any = self.metadata.get("versions") or []
        return cast(list[dict[str, Any]], versions)

    # -- uploads -----------------------------------------------------------

    def save_upload(
        self, kind: Literal["video", "screenshots"], data_url: str
    ) -> Path:
        match = _DATA_URL_PATTERN.match(data_url)
        if match is None:
            raise ValueError("Upload is not a base64 data URL")
        try:
            data = base64.b64decode(match.group(2), validate=False)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("Upload is not valid base64") from exc
        extension = mimetypes.guess_extension(match.group(1) or "") or ".bin"
        directory = self.path / "uploads" / kind
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{uuid.uuid4().hex[:12]}{extension}"
        target.write_bytes(data)
        return target

    # -- versions ----------------------------------------------------------

    def has_version(self, ui_commit_hash: str) -> bool:
        if not _UI_COMMIT_HASH_PATTERN.match(ui_commit_hash):
            return False
        return self._version_sha(ui_commit_hash) is not None

    def version_number(self, ui_commit_hash: str) -> int:
        for version in self._versions():
            if version.get("ui_commit_hash") == ui_commit_hash:
                return int(version["n"])
        raise KeyError(ui_commit_hash)

    def option_codes(self, ui_commit_hash: str) -> list[str]:
        sha = self._require_version_sha(ui_commit_hash)
        numbered: list[tuple[int, str]] = []
        for name in self._git("ls-tree", "-r", "--name-only", sha).splitlines():
            match = _MOCK_PATH_PATTERN.match(name)
            if match:
                numbered.append((int(match.group(1)), name))
        return [self._git_raw("show", f"{sha}:{name}") for _, name in sorted(numbered)]

    def commit_version(
        self,
        *,
        ui_commit_hash: str,
        parent_ui_commit_hash: str | None,
        option_codes: list[str],
        message: str,
    ) -> str:
        _check_ui_commit_hash(ui_commit_hash)
        with _lock_for(self.path):
            parent_sha = (
                self._version_sha(parent_ui_commit_hash)
                if parent_ui_commit_hash
                and _UI_COMMIT_HASH_PATTERN.match(parent_ui_commit_hash)
                else None
            )
            metadata = self.metadata
            versions = self._versions()
            entry: dict[str, Any] = {
                "n": len(versions) + 1,
                "ui_commit_hash": ui_commit_hash,
                "parent": parent_ui_commit_hash,
                "sha": None,
                "message": message,
            }
            metadata["versions"] = [*versions, entry]
            self._write_metadata(metadata)

            files = {
                _mock_path(index + 1): code for index, code in enumerate(option_codes)
            }
            for number, code in enumerate(option_codes, start=1):
                target = self.path / _mock_path(number)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(code, encoding="utf-8")
            stale = self._stale_design_dirs(parent_sha, len(option_codes))
            for directory in stale:
                shutil.rmtree(self.path / directory, ignore_errors=True)
            files[".gitignore"] = _GITIGNORE
            files["stack.yaml"] = (self.path / "stack.yaml").read_text(encoding="utf-8")

            sha = self._commit(parent_sha, files, message, remove=stale)
            self._git("update-ref", _VERSION_REF_PREFIX + ui_commit_hash, sha)
            self._git("update-ref", "refs/heads/main", sha)
            self._sync_index()

            entry["sha"] = sha
            self._write_metadata(metadata)
            return sha

    def update_version(
        self, ui_commit_hash: str, option_index: int, code: str, message: str
    ) -> str:
        with _lock_for(self.path):
            base_sha = self._require_version_sha(ui_commit_hash)
            path = _mock_path(option_index + 1)
            target = self.path / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(code, encoding="utf-8")

            sha = self._commit(base_sha, {path: code}, message)
            self._git("update-ref", _VERSION_REF_PREFIX + ui_commit_hash, sha)
            self._git("update-ref", "refs/heads/main", sha)
            self._sync_index()

            metadata = self.metadata
            for version in self._versions_of(metadata):
                if version.get("ui_commit_hash") == ui_commit_hash:
                    version["sha"] = sha
            self._write_metadata(metadata)
            return sha

    def checkout_version(self, ui_commit_hash: str, dest: Path) -> None:
        sha = self._require_version_sha(ui_commit_hash)
        archive = subprocess.run(
            ["git", "archive", "--format=tar", sha],
            check=True,
            capture_output=True,
            cwd=self.path,
            env=self._env(),
        ).stdout
        dest.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["tar", "-x", "-C", str(dest)], input=archive, check=True, capture_output=True
        )

    def commit_app(self, ui_commit_hash: str, message: str) -> str:
        """Commit ``op*/app/**`` from the working tree on top of a version."""
        with _lock_for(self.path):
            base_sha = self._require_version_sha(ui_commit_hash)
            with self._temp_index(base_sha) as env:
                self._git("add", "-A", "--", ":(glob)op*/app/**", env=env)
                tree = self._git("write-tree", env=env)
            sha = self._git("commit-tree", tree, "-p", base_sha, "-m", message)
            self._git("update-ref", "refs/heads/main", sha)
            self._sync_index()
            return sha

    # -- git plumbing --------------------------------------------------------

    def _env(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        return {**os.environ, **_GIT_IDENTITY, **(extra or {})}

    def _git(self, *args: str, env: dict[str, str] | None = None) -> str:
        return self._git_raw(*args, env=env).strip()

    def _git_raw(self, *args: str, env: dict[str, str] | None = None) -> str:
        # safe.directory: the runs volume may be owned by another uid.
        return subprocess.run(
            ["git", "-c", "safe.directory=*", *args],
            check=True,
            capture_output=True,
            text=True,
            cwd=self.path,
            env=env if env is not None else self._env(),
        ).stdout

    def _version_sha(self, ui_commit_hash: str) -> str | None:
        result = subprocess.run(
            [
                "git",
                "-c",
                "safe.directory=*",
                "rev-parse",
                "--verify",
                "--quiet",
                _VERSION_REF_PREFIX + ui_commit_hash,
            ],
            capture_output=True,
            text=True,
            cwd=self.path,
            env=self._env(),
        )
        return result.stdout.strip() if result.returncode == 0 else None

    def _require_version_sha(self, ui_commit_hash: str) -> str:
        _check_ui_commit_hash(ui_commit_hash)
        sha = self._version_sha(ui_commit_hash)
        if sha is None:
            raise KeyError(ui_commit_hash)
        return sha

    def _versions_of(self, metadata: dict[str, Any]) -> list[dict[str, Any]]:
        versions: Any = metadata.get("versions") or []
        return cast(list[dict[str, Any]], versions)

    def _stale_design_dirs(self, base_sha: str | None, option_count: int) -> list[str]:
        """``op<M>/design`` dirs (in the base commit or on disk) with M > count."""
        numbers: set[int] = set()
        if base_sha:
            for name in self._git("ls-tree", "-r", "--name-only", base_sha).splitlines():
                match = _MOCK_PATH_PATTERN.match(name)
                if match:
                    numbers.add(int(match.group(1)))
        for child in self.path.glob("op*/design"):
            match = re.match(r"^op(\d+)$", child.parent.name)
            if match:
                numbers.add(int(match.group(1)))
        return [f"op{n}/design" for n in sorted(numbers) if n > option_count]

    def _temp_index(self, base_sha: str | None) -> "_TempIndex":
        return _TempIndex(self, base_sha)

    def _commit(
        self,
        base_sha: str | None,
        files: dict[str, str],
        message: str,
        remove: list[str] | None = None,
    ) -> str:
        with self._temp_index(base_sha) as env:
            for directory in remove or []:
                self._git(
                    "rm", "-r", "-q", "--cached", "--ignore-unmatch", "--", directory, env=env
                )
            for path, content in files.items():
                blob = subprocess.run(
                    ["git", "-c", "safe.directory=*", "hash-object", "-w", "--stdin"],
                    input=content.encode("utf-8"),
                    check=True,
                    capture_output=True,
                    cwd=self.path,
                    env=env,
                ).stdout.decode().strip()
                self._git(
                    "update-index", "--add", "--cacheinfo", f"100644,{blob},{path}", env=env
                )
            tree = self._git("write-tree", env=env)
        args = ["commit-tree", tree, "-m", message]
        if base_sha:
            args[2:2] = ["-p", base_sha]
        return self._git(*args)

    def _sync_index(self) -> None:
        # Keep the real index on main so `git status` in the run dir is useful.
        self._git("read-tree", "refs/heads/main")


class _TempIndex:
    """Context manager yielding a git env bound to a throwaway index file."""

    def __init__(self, workspace: RunWorkspace, base_sha: str | None) -> None:
        self._workspace = workspace
        self._base_sha = base_sha
        self._path: str | None = None

    def __enter__(self) -> dict[str, str]:
        handle, self._path = tempfile.mkstemp(
            prefix="s2c-index-", dir=self._workspace.path / ".git"
        )
        os.close(handle)
        os.unlink(self._path)
        env = self._workspace._env({"GIT_INDEX_FILE": self._path})
        if self._base_sha:
            self._workspace._git("read-tree", self._base_sha, env=env)
        else:
            self._workspace._git("read-tree", "--empty", env=env)
        return env

    def __exit__(self, *exc: object) -> None:
        if self._path and os.path.exists(self._path):
            os.unlink(self._path)
