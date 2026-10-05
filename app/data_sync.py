"""Two-way sync of the eye-image library with the `data` branch on GitHub.

Downloading works without a token because the repository is public. Uploading
needs a GitHub token with Contents read/write on this repository.

Each local folder maps to a top-level folder in the `data` branch. A small state
file remembers the git blob SHA of every file at the last sync, so the sync can
tell which side changed a file:

* changed only on GitHub  -> download it
* changed only locally    -> upload it
* changed on both         -> the local copy wins (uploaded)
* deleted on one side     -> delete it on the other side, if the other side is unchanged
"""

from __future__ import annotations

import base64
import hashlib
import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

REPO = "apinanautan/blythe-a4-maker"
BRANCH = "data"
API = f"https://api.github.com/repos/{REPO}"
RAW = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}"
SYNC_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".psd"}
MAX_FILE_BYTES = 95 * 1024 * 1024  # GitHub rejects files over 100 MB
SYNC_SUBFOLDERS = {"_custom_a4"}  # only these subfolders sync; caches and old folders stay local

_lock = threading.Lock()


@dataclass
class SyncResult:
    downloaded: list[str] = field(default_factory=list)
    uploaded: list[str] = field(default_factory=list)
    deleted_local: list[str] = field(default_factory=list)
    deleted_remote: list[str] = field(default_factory=list)
    skipped_large: list[str] = field(default_factory=list)
    upload_needs_token: bool = False

    @property
    def local_changed(self) -> bool:
        return bool(self.downloaded or self.deleted_local)

    def summary(self) -> str:
        parts = []
        if self.downloaded:
            parts.append(f"โหลดลง {len(self.downloaded)}")
        if self.uploaded:
            parts.append(f"อัปขึ้น {len(self.uploaded)}")
        if self.deleted_local or self.deleted_remote:
            parts.append(f"ลบ {len(self.deleted_local) + len(self.deleted_remote)}")
        if self.skipped_large:
            parts.append(f"ไฟล์ใหญ่เกิน 95MB ข้าม {len(self.skipped_large)}")
        text = " • ".join(parts) if parts else "ข้อมูลตรงกับ GitHub แล้ว"
        if self.upload_needs_token:
            text += " • มีไฟล์ใหม่รออัปขึ้น (ใส่ GitHub token ในตั้งค่า)"
        return text


def git_blob_sha(data: bytes) -> str:
    """The SHA git uses for a file's content, so it matches GitHub's tree listing."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def scan_local(
    folders: dict[str, Path],
    hash_cache: dict[str, list] | None = None,
) -> tuple[dict[str, str], dict[str, Path], list[str]]:
    """Return {remote_path: sha}, {remote_path: local_path} and too-large files.

    hash_cache maps a local path to [size, mtime_ns, sha] so unchanged files
    (large PSDs especially) are not re-read on every sync. It is updated in place.
    """
    cache = hash_cache if hash_cache is not None else {}
    shas: dict[str, str] = {}
    paths: dict[str, Path] = {}
    large: list[str] = []
    for prefix, root in folders.items():
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            relative = path.relative_to(root)
            if not path.is_file() or path.suffix.lower() not in SYNC_EXTENSIONS or path.name.startswith("."):
                continue
            if len(relative.parts) > 2 or (len(relative.parts) == 2 and relative.parts[0] not in SYNC_SUBFOLDERS):
                continue
            remote = f"{prefix}/{relative.as_posix()}"
            stat = path.stat()
            if stat.st_size > MAX_FILE_BYTES:
                large.append(remote)
                continue
            cached = cache.get(str(path))
            if cached and cached[0] == stat.st_size and cached[1] == stat.st_mtime_ns:
                sha = cached[2]
            else:
                sha = git_blob_sha(path.read_bytes())
                cache[str(path)] = [stat.st_size, stat.st_mtime_ns, sha]
            shas[remote] = sha
            paths[remote] = path
    return shas, paths, large


def local_path_for(remote: str, folders: dict[str, Path]) -> Path | None:
    prefix, _, rest = remote.partition("/")
    root = folders.get(prefix)
    if root is None or not rest:
        return None
    target = root.joinpath(*rest.split("/"))
    if not target.resolve().is_relative_to(root.resolve()):
        return None
    return target


def plan_sync(
    local: dict[str, str],
    remote: dict[str, str],
    state: dict[str, str],
) -> tuple[list[str], list[str], list[str], list[str]]:
    """Decide (download, upload, delete_local, delete_remote) from three snapshots."""
    download, upload, delete_local, delete_remote = [], [], [], []
    for path in sorted(set(local) | set(remote) | set(state)):
        here, there, before = local.get(path), remote.get(path), state.get(path)
        if here == there:
            continue
        local_changed = here != before
        remote_changed = there != before
        if local_changed:
            if here is None:
                if not remote_changed:
                    delete_remote.append(path)
                else:
                    download.append(path)  # deleted here but edited on GitHub: keep the edit
            else:
                upload.append(path)
        elif remote_changed:
            if there is None:
                delete_local.append(path)
            else:
                download.append(path)
    return download, upload, delete_local, delete_remote


class GitHubData:
    def __init__(self, token: str = "") -> None:
        self.token = token.strip()

    def _request(self, method: str, url: str, body: dict | None = None) -> dict | list | None:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("User-Agent", "Blythe-Eye-Maker-Sync")
        request.add_header("Accept", "application/vnd.github+json")
        if data is not None:
            request.add_header("Content-Type", "application/json")
        if self.token:
            request.add_unredirected_header("Authorization", f"Bearer {self.token}")
        with urllib.request.urlopen(request, timeout=120) as response:
            raw = response.read()
        return json.loads(raw) if raw else None

    def head_sha(self) -> str | None:
        try:
            ref = self._request("GET", f"{API}/git/ref/heads/{BRANCH}")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise
        return ref["object"]["sha"]

    def remote_files(self, commit_sha: str | None) -> dict[str, str]:
        if not commit_sha:
            return {}
        tree = self._request("GET", f"{API}/git/trees/{commit_sha}?recursive=1")
        return {item["path"]: item["sha"] for item in tree.get("tree", []) if item.get("type") == "blob"}

    def download(self, remote: str, commit_sha: str) -> bytes:
        url = f"https://raw.githubusercontent.com/{REPO}/{commit_sha}/{urllib.parse.quote(remote)}"
        request = urllib.request.Request(url, headers={"User-Agent": "Blythe-Eye-Maker-Sync"})
        with urllib.request.urlopen(request, timeout=300) as response:
            return response.read()

    def commit(
        self,
        parent_sha: str | None,
        uploads: dict[str, Path],
        deletions: list[str],
        message: str,
    ) -> str:
        entries = []
        for remote, path in uploads.items():
            blob = self._request(
                "POST",
                f"{API}/git/blobs",
                {"content": base64.b64encode(path.read_bytes()).decode("ascii"), "encoding": "base64"},
            )
            entries.append({"path": remote, "mode": "100644", "type": "blob", "sha": blob["sha"]})
        if parent_sha:
            entries += [{"path": remote, "mode": "100644", "type": "blob", "sha": None} for remote in deletions]
        tree_body: dict = {"tree": entries}
        if parent_sha:
            tree_body["base_tree"] = self._request("GET", f"{API}/git/commits/{parent_sha}")["tree"]["sha"]
        tree = self._request("POST", f"{API}/git/trees", tree_body)
        new_commit = self._request(
            "POST",
            f"{API}/git/commits",
            {"message": message, "tree": tree["sha"], "parents": [parent_sha] if parent_sha else []},
        )
        if parent_sha:
            self._request("PATCH", f"{API}/git/refs/heads/{BRANCH}", {"sha": new_commit["sha"]})
        else:
            self._request("POST", f"{API}/git/refs", {"ref": f"refs/heads/{BRANCH}", "sha": new_commit["sha"]})
        return new_commit["sha"]


def _load_state(state_file: Path) -> dict[str, str]:
    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
        return {str(key): str(value) for key, value in data.items()} if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_state(state_file: Path, state: dict) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    temp = state_file.with_suffix(".tmp")
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    temp.replace(state_file)


def sync(folders: dict[str, Path], state_file: Path, token: str = "", client: GitHubData | None = None) -> SyncResult:
    """Run one full two-way sync. Only one sync runs at a time."""
    with _lock:
        github = client or GitHubData(token)
        result = SyncResult()
        state = _load_state(state_file)
        head = github.head_sha()
        remote = github.remote_files(head)
        remote = {path: sha for path, sha in remote.items() if path.partition("/")[0] in folders}
        hash_cache_file = state_file.with_name("data_sync_hashes.json")
        try:
            hash_cache = json.loads(hash_cache_file.read_text(encoding="utf-8"))
            if not isinstance(hash_cache, dict):
                hash_cache = {}
        except (OSError, ValueError):
            hash_cache = {}
        local, local_paths, result.skipped_large = scan_local(folders, hash_cache)
        live = {str(path) for path in local_paths.values()}
        hash_cache = {key: value for key, value in hash_cache.items() if key in live}
        _save_state(hash_cache_file, hash_cache)
        download, upload, delete_local, delete_remote = plan_sync(local, remote, state)

        for path in download:
            target = local_path_for(path, folders)
            if target is None:
                continue
            data = github.download(path, head)
            target.parent.mkdir(parents=True, exist_ok=True)
            temp = target.with_name(f".sync_{target.name}")
            temp.write_bytes(data)
            temp.replace(target)
            state[path] = remote[path]
            result.downloaded.append(path)
        for path in delete_local:
            target = local_path_for(path, folders)
            if target is not None:
                target.unlink(missing_ok=True)
            state.pop(path, None)
            result.deleted_local.append(path)
        for path, sha in remote.items():
            if local.get(path) == sha:
                state[path] = sha  # already identical on both sides
        for path in [path for path in state if path not in remote and path not in local]:
            state.pop(path)  # gone on both sides
        _save_state(state_file, state)

        if upload or delete_remote:
            if not github.token:
                result.upload_needs_token = True
                return result
            github.commit(
                head,
                {path: local_paths[path] for path in upload},
                delete_remote,
                f"Sync eye library: {len(upload)} updated, {len(delete_remote)} deleted",
            )
            for path in upload:
                state[path] = local[path]
            for path in delete_remote:
                state.pop(path, None)
            result.uploaded, result.deleted_remote = upload, delete_remote
            _save_state(state_file, state)
        return result
