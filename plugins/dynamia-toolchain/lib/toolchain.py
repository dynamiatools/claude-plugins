"""Shared plumbing for jdk-tool and node-tool: download with a checksum, extract safely, where tools live, shell environment.

Standard library only. Nothing here runs a downloaded program except `run`, which the user asks for by name.
Downloads go over https (plain http only to localhost, for tests), always carry a User-Agent (Foojay answers 403 without one),
and are installed only when the published checksum matches.
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import sys
import tarfile
import tempfile
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

UA = "dynamia-toolchain/0.1"
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")
LOOPBACK = {"localhost", "127.0.0.1", "::1"}


class ToolError(Exception):
    """A failure with a message for the user."""


def die(message: str):
    raise ToolError(message)


def valid_name(kind: str, value: str) -> str:
    if not NAME.match(value or "") or ".." in value:
        die(f"invalid {kind} '{value}': letters, digits, '.', '_', '+' and '-' only")
    return value


# ---------------------------------------------------------------- platform
def platform_ids() -> tuple[str, str]:
    """(os, cpu) in the words Foojay uses: linux|macos and x64|aarch64."""
    system = {"linux": "linux", "darwin": "macos"}.get(sys.platform)
    if not system:
        die(f"unsupported operating system: {sys.platform} (Linux and macOS only)")
    machine = platform.machine().lower()
    arch = {"x86_64": "x64", "amd64": "x64", "arm64": "aarch64", "aarch64": "aarch64"}.get(machine)
    if not arch:
        die(f"unsupported CPU: {machine}")
    return system, arch


def is_musl() -> bool:
    return bool(glob.glob("/lib/ld-musl-*") or glob.glob("/usr/lib/ld-musl-*"))


# ---------------------------------------------------------------- network
def _check_url(url: str) -> None:
    parts = urllib.parse.urlparse(url)
    if parts.scheme == "https" or (parts.scheme == "http" and parts.hostname in LOOPBACK):
        return
    die(f"refusing a download over {parts.scheme or 'an unknown scheme'}: only https (or http to localhost) is allowed ({url[:80]})")


def _open(url: str):
    _check_url(url)
    try:
        return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=60)
    except (OSError, ValueError) as e:
        die(f"could not fetch {url[:100]}: {e}")


def get_json(url: str):
    with _open(url) as r:
        try:
            return json.load(r)
        except ValueError:
            die(f"{url[:100]} did not return JSON")


def get_text(url: str) -> str:
    with _open(url) as r:
        return r.read().decode("utf-8", "replace")


def download(url: str, target: Path, checksum: str, algo: str = "sha256") -> None:
    """Stream `url` to `target`; delete it and fail unless its `algo` digest equals `checksum`."""
    if not checksum:
        die("no checksum is published for this download, so it is not installed")
    if algo not in ("sha256", "sha512", "sha1"):
        die(f"unsupported checksum type '{algo}'")
    digest = hashlib.new(algo)
    with _open(url) as r, open(target, "wb") as out:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            digest.update(chunk)
            out.write(chunk)
    if digest.hexdigest().lower() != checksum.strip().lower():
        target.unlink(missing_ok=True)
        die(f"checksum mismatch for {Path(urllib.parse.urlparse(url).path).name}: not installed")


# ---------------------------------------------------------------- archives
def _inside(base: Path, candidate: Path) -> bool:
    base, candidate = base.resolve(), candidate.resolve()
    return candidate == base or base in candidate.parents


def safe_extract(archive: Path, dest: Path) -> None:
    """Extract a .tar.* or .zip into `dest`, refusing absolute paths, '..', links that leave it and device files."""
    dest.mkdir(parents=True, exist_ok=True)
    if tarfile.is_tarfile(archive):
        with tarfile.open(archive) as tar:
            for m in tar.getmembers():
                p = Path(m.name)
                if p.is_absolute() or ".." in p.parts:
                    die(f"unsafe path in the archive: {m.name}")
                if m.isdev() or m.isfifo():
                    die(f"unsafe file type in the archive: {m.name}")
                if m.issym() or m.islnk():
                    link = Path(m.linkname) if m.islnk() else p.parent / m.linkname
                    if Path(m.linkname).is_absolute() or not _inside(dest, dest / link):
                        die(f"link leaves the install folder: {m.name} -> {m.linkname}")
            tar.extractall(dest, filter="data") if hasattr(tarfile, "data_filter") else tar.extractall(dest)
    elif zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as z:
            for n in z.namelist():
                p = Path(n)
                if p.is_absolute() or ".." in p.parts:
                    die(f"unsafe path in the archive: {n}")
            z.extractall(dest)
            for info in z.infolist():   # zipfile drops permissions: restore them, or bin/gradle would not run
                mode = (info.external_attr >> 16) & 0o777
                if mode and not info.is_dir():
                    os.chmod(dest / info.filename, mode)
    else:
        die("the download is not a tar or zip archive")


def find_home(root: Path, marker: str, depth: int = 3) -> Path | None:
    """The folder under `root` that has `marker` (e.g. bin/java): the JDK or Node home, also inside macOS's Contents/Home."""
    exe = (marker + ".exe") if sys.platform == "win32" else marker
    stack = [(root, 0)]
    while stack:
        d, level = stack.pop(0)
        if (d / exe).is_file() or (d / marker).is_file():
            return d
        if level < depth:
            stack.extend((c, level + 1) for c in sorted(d.iterdir()) if c.is_dir() and not c.is_symlink())
    return None


def install_archive(archive: Path, folder: Path, marker: str) -> Path:
    """Extract into a temporary folder next to `folder`, then move the tool's home to `folder`; nothing is left half installed."""
    folder.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=".install-", dir=folder.parent))
    try:
        safe_extract(archive, tmp)
        home = find_home(tmp, marker)
        if home is None:
            die(f"the archive has no {marker}: not a valid install")
        shutil.move(str(tmp), str(folder)) if home == tmp else shutil.move(str(home), str(folder))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return folder


# ---------------------------------------------------------------- where things live
def repo_root(start: Path | None = None) -> Path | None:
    p = (start or Path.cwd()).resolve()
    for d in (p, *p.parents):
        if (d / ".git").exists():
            return d
    return None


def install_base(where: str, folder_name: str) -> Path:
    """`home` -> ~/<folder_name>, `project` -> <repo or current folder>/<folder_name>, anything else is a folder path."""
    if where == "home":
        return Path.home() / folder_name
    if where == "project":
        return (repo_root() or Path.cwd()) / folder_name
    return Path(os.path.expanduser(where)).resolve()


def ensure_ignored(folder_name: str) -> str:
    """Add `<folder_name>/` to the repo's .gitignore once. Returns a one-line note for the user."""
    root = repo_root()
    if root is None:
        return f"not inside a git repo: nothing to ignore (the folder is {folder_name}/)"
    entry = folder_name.rstrip("/") + "/"
    gi = root / ".gitignore"
    lines = gi.read_text().splitlines() if gi.is_file() else []
    if any(x.strip() in (entry, entry.rstrip("/"), "/" + entry, "/" + entry.rstrip("/")) for x in lines):
        return f"{entry} is already in .gitignore"
    with open(gi, "a") as f:
        f.write(("" if not lines or gi.read_text().endswith("\n") else "\n") + entry + "\n")
    return f"added {entry} to {gi}"


def installed(base_dirs: list[tuple[str, Path]], marker: str) -> list[dict]:
    out = []
    for label, base in base_dirs:
        if not base.is_dir():
            continue
        for d in sorted(base.iterdir()):
            if d.is_dir() and not d.name.startswith(".") and (find_home(d, marker, 2) is not None):
                out.append({"name": d.name, "where": label, "path": str(find_home(d, marker, 2))})
    return out


def resolve_installed(spec: str, base_dirs: list[tuple[str, Path]], marker: str) -> Path:
    """`spec` is an installed name (or a unique prefix) or a path to a home."""
    p = Path(os.path.expanduser(spec))
    if os.sep in spec and p.is_dir():
        home = find_home(p, marker, 2)
        if home:
            return home
        die(f"{spec} has no {marker}")
    found = installed(base_dirs, marker)
    exact = [x for x in found if x["name"] == spec]
    pool = exact or [x for x in found if x["name"].startswith(spec)]
    if not pool:
        die(f"nothing installed matches '{spec}' (see: list)")
    if len(pool) > 1:
        die(f"'{spec}' is ambiguous: " + ", ".join(f"{x['name']} ({x['where']})" for x in pool))
    return Path(pool[0]["path"])


# ---------------------------------------------------------------- shell environment
# An environment is (vars, path_dirs): variables to set and folders to put first in PATH.
def env_for_run(vars: dict[str, str], dirs: list[Path]) -> dict[str, str]:
    path = os.pathsep.join([str(d) for d in dirs] + [os.environ.get("PATH", "")])
    return {**os.environ, **vars, "PATH": path}


def shell_env(vars: dict[str, str], dirs: list[Path], shell: str = "sh") -> str:
    lines = []
    for k, v in vars.items():
        lines.append({"sh": f"export {k}={shlex.quote(v)}", "fish": f"set -gx {k} {shlex.quote(v)}", "powershell": f"$env:{k} = '{v}'"}[shell])
    joined = ":".join(shlex.quote(str(d)) for d in dirs)
    lines.append({"sh": f"export PATH={joined}:\"$PATH\"", "fish": f"set -gx PATH {' '.join(shlex.quote(str(d)) for d in dirs)} $PATH",
                  "powershell": "$env:PATH = '" + ";".join(str(d) for d in dirs) + "' + [IO.Path]::PathSeparator + $env:PATH"}[shell])
    return "\n".join(lines)


def shell_unload(vars: dict[str, str], dirs: list[Path]) -> str:
    """sh lines that undo `shell_env`: unset the variables and drop the folders from PATH."""
    lines = [f"unset {k}" for k in vars]
    for d in dirs:
        lines.append(f"PATH=$(printf %s \"$PATH\" | tr ':' '\\n' | grep -vxF {shlex.quote(str(d))} | paste -sd: -); export PATH")
    return "\n".join(lines)


def run_with(vars: dict[str, str], dirs: list[Path], command: list[str]) -> int:
    if not command:
        die("run needs a command after --")
    env = env_for_run(vars, dirs)
    exe = shutil.which(command[0], path=env["PATH"])
    if exe is None:
        die(f"command not found: {command[0]}")
    os.execve(exe, command, env)


def parse_where(argv: list[str]) -> tuple[str, list[str]]:
    """Pull `--where home|project|<folder>` (and the `--project` shortcut) out of argv; the default is home."""
    where, rest, i = "home", [], 0
    while i < len(argv):
        if argv[i] == "--where" and i + 1 < len(argv):
            where, i = argv[i + 1], i + 2
        elif argv[i] == "--project":
            where, i = "project", i + 1
        else:
            rest.append(argv[i])
            i += 1
    return where, rest


def fmt_size(n: int) -> str:
    return f"{n / (1 << 20):.0f} MB"
