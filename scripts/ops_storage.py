"""Archive-on-change storage and rollback-safe publication; no model dependencies."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Callable, Mapping

DEFAULT_ARCHIVE_ROOT = Path.home() / "Football_archive_ops"


def _archive_dir(archive_root: Path | None = None) -> Path:
    root = Path(archive_root) if archive_root is not None else DEFAULT_ARCHIVE_ROOT
    root.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="archive_", dir=root))


def archive_paths(paths, archive_root: Path | None = None) -> tuple[Path | None, dict[Path, Path]]:
    existing = [Path(p) for p in paths if Path(p).exists()]
    if not existing:
        return None, {}
    archive = _archive_dir(archive_root)
    saved = {}
    for path in existing:
        token = hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:12]
        target = archive / (token + "_" + path.name)
        if path.is_dir():
            shutil.copytree(path, target)
        else:
            shutil.copy2(path, target)
            if target.read_bytes() != path.read_bytes():
                raise OSError(f"archive verification failed: {path}")
        saved[path] = target
    (archive / "manifest.json").write_text(json.dumps({str(k): str(v) for k, v in saved.items()}, indent=2))
    return archive, saved


def atomic_write_files(payloads: Mapping[Path, bytes], archive_root: Path | None = None) -> Path | None:
    """Stage every changed file, archive old bytes, replace; restore all files on failure.

    Identical bytes are left untouched, so reruns do not accumulate identical archives.
    Files are individually atomic; a dated snapshot uses publish_snapshot for bundle publication.
    """
    changed = {Path(p): data for p, data in payloads.items()
               if not Path(p).is_file() or Path(p).read_bytes() != data}
    if not changed:
        return None
    staged = {}
    archive = None
    saved = {}
    applied = []
    try:
        for path, data in changed.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".write-", delete=False) as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
                staged[path] = Path(f.name)
        archive, saved = archive_paths(changed, archive_root)
        for path, temporary in staged.items():
            os.replace(temporary, path)
            applied.append(path)
        return archive
    except BaseException:
        for path in reversed(applied):
            if path in saved:
                with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".restore-", delete=False) as f:
                    temporary = Path(f.name)
                shutil.copy2(saved[path], temporary)
                os.replace(temporary, path)
            else:
                path.unlink(missing_ok=True)
        raise
    finally:
        for temporary in staged.values():
            temporary.unlink(missing_ok=True)


def publish_snapshot(stage: Path, destination: Path, archive_root: Path | None = None,
                     promote: Callable | None = None) -> Path | None:
    """Publish one already-validated directory, retaining an external old-bundle archive.

    The old directory is moved aside only after its archive succeeds. If promotion fails,
    restore it before propagating the error. Readers can briefly see no directory during the
    two renames, but never a bundle assembled from old and new data. Pipeline files belong to
    the caller, which copies them to stage and writes the current Run report after publication.
    `promote` is a narrow failure-injection hook; rollback always uses the real os.replace.
    """
    stage, destination = Path(stage), Path(destination)
    if not stage.is_dir() or stage == destination:
        raise ValueError("snapshot stage must be a separate existing directory")
    archive, _ = archive_paths([destination], archive_root)
    backup = None
    try:
        if destination.exists():
            backup = Path(tempfile.mkdtemp(prefix=".snapshot-rollback-", dir=destination.parent))
            backup.rmdir()
            os.replace(destination, backup)
        (promote or os.replace)(stage, destination)
    except BaseException:
        if backup is not None and backup.exists():
            os.replace(backup, destination)
        raise
    if backup is not None:
        shutil.rmtree(backup)
    return archive
