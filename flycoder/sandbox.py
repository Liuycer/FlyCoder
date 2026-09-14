"""Independent Git snapshot. File isolation, NOT an OS security boundary."""
import hashlib
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess


SKIP = {".git", ".venv", "venv", "__pycache__", "node_modules", ".pytest_cache"}
MAX_FILE = 200_000
MAX_REPO = 5_000_000


def relative_path(name: str) -> Path:
    p = PurePosixPath(name)
    if not name or p.is_absolute() or ".." in p.parts or "\\" in name:
        raise ValueError("Unsafe relative path: " + name)
    if any(part.startswith(".") for part in p.parts):
        raise ValueError("Hidden paths are excluded: " + name)
    return Path(*p.parts)


class GitSandbox:
    def __init__(self, source: Path, destination: Path, editable: list):
        self.source = source.resolve()
        self.root = destination.resolve()
        self.editable = set(editable)
        for name in editable:
            relative_path(name)
            if "tests" in Path(name).parts or Path(name).name.startswith("test_"):
                raise ValueError("Test files cannot be editable in this prototype")
        if not self.source.is_dir():
            raise ValueError("Repository directory does not exist")
        if self.root == self.source or self.source in self.root.parents:
            raise ValueError("Sandbox must be outside the source repository")
        if self.root.exists():
            raise ValueError("Sandbox destination must be new")

    def git(self, *args: str) -> str:
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
               "HOME": str(self.root.parent), "GIT_CONFIG_NOSYSTEM": "1",
               "GIT_CONFIG_GLOBAL": os.devnull, "LC_ALL": "C"}
        return subprocess.run(
            ["git", "-c", "core.hooksPath=/dev/null", *args], cwd=self.root,
            env=env, capture_output=True, text=True, check=True, timeout=15,
        ).stdout

    def create(self) -> None:
        self.root.mkdir(parents=True)
        total = 0
        for directory, dirs, files in os.walk(self.source, followlinks=False):
            dirs[:] = sorted(d for d in dirs if d not in SKIP and not d.startswith("."))
            base = Path(directory)
            if any((base / d).is_symlink() for d in dirs):
                raise ValueError("Symbolic link directories are unsupported")
            for name in sorted(files):
                if name.startswith(".") or name.endswith((".pyc", ".pem", ".key")):
                    continue
                path = base / name
                if not stat.S_ISREG(path.lstat().st_mode):
                    raise ValueError("Only regular files may be snapshotted")
                size = path.stat().st_size
                total += size
                if size > MAX_FILE or total > MAX_REPO:
                    raise ValueError("Small-repository size limit exceeded")
                target = self.root / path.relative_to(self.source)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
        for name in self.editable:
            if not (self.root / relative_path(name)).is_file():
                raise ValueError("Editable file is missing: " + name)
        self.git("init", "-q")
        self.git("add", "--all")
        self.git("-c", "user.name=FlyCoder", "-c", "user.email=flycoder@localhost",
                 "-c", "commit.gpgsign=false", "commit", "-qm", "Input snapshot")

    def context(self) -> dict:
        result = {}
        for name in self.git("ls-files", "-z").split("\0"):
            if name:
                p = self.root / name
                if p.is_symlink() or p.resolve() != p or not p.is_file() or p.stat().st_size > MAX_FILE:
                    raise ValueError("Snapshot file changed type or size")
                try:
                    result[name] = p.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    continue
        if sum(len(v) for v in result.values()) > MAX_REPO:
            raise ValueError("Context too large")
        return result

    def apply(self, changes: dict) -> None:
        if not isinstance(changes, dict) or not changes:
            raise ValueError("Expected nonempty file replacement mapping")
        validated = []
        for name, content in changes.items():
            if name not in self.editable or not isinstance(content, str):
                raise ValueError("Edit outside explicit file allowlist")
            p = self.root / relative_path(name)
            if p.is_symlink() or p.resolve() != p or not p.is_file():
                raise ValueError("Edit target must be an existing regular sandbox file")
            if len(content.encode("utf-8")) > MAX_FILE:
                raise ValueError("Replacement too large")
            validated.append((p, content))
        for p, content in validated:
            p.write_text(content, encoding="utf-8")

    def diff(self) -> str:
        return self.git("diff", "--no-ext-diff", "--no-textconv", "HEAD", "--")

    def fingerprint(self) -> str:
        h = hashlib.sha256()
        for name in sorted(self.git("ls-files", "-z").split("\0")):
            if name:
                p = self.root / name
                if p.resolve() != p or not p.is_file() or p.stat().st_size > MAX_FILE:
                    raise ValueError("Snapshot file changed type or size")
                h.update(name.encode() + b"\0" + p.read_bytes() + b"\0")
        return h.hexdigest()

    def changed_count(self) -> int:
        return len(self.git("diff", "--name-only", "HEAD").splitlines())
