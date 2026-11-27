"""Layer-1 Scoped File Metadata Index, Fast Search, Session Working Set & Safe Open (B10, DEC-032, NFR-16).

Strictly OS-independent (zero Win32/ctypes imports); delegates path safety & document opening to Ports.
"""

from __future__ import annotations

import difflib
import hashlib
import os
import re
import threading
import time
import unicodedata
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from jarvis.domain.models import ErrorCode
from jarvis.domain.ports import (
    ClockPort,
    FileOpenerPort,
    FileOpenReceipt,
    FilesystemSafetyPort,
    is_safe_document_open_extension,
)
from jarvis.infrastructure.dual_db import DualSqliteManager

# Excluded OS, credential, VCS, and build-artifact directories (DEC-032)
EXCLUDED_DIR_NAMES: frozenset[str] = frozenset(
    {
        ".ssh",
        ".gnupg",
        ".aws",
        ".azure",
        ".kube",
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        ".venv",
        "venv",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "$recycle.bin",
        "system volume information",
        "windows",
        "programdata",
        "recovery",
    }
)

EXCLUDED_SECRET_FILENAMES: frozenset[str] = frozenset(
    {
        ".env",
        ".netrc",
        "id_rsa",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
        "credentials",
        "credentials.json",
        "secrets.json",
    }
)

EXCLUDED_SECRET_SUFFIXES: frozenset[str] = frozenset(
    {".pem", ".key", ".pfx", ".p12", ".kdbx", ".ppk"}
)


class FileIndexError(ValueError):
    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class FileMetadataHit:
    file_id: str
    root_id: str
    root_path: str
    relative_path: str
    display_name: str
    ext: str
    size_bytes: int
    mtime_ns: int
    availability: Literal["available", "unavailable"]
    score: float


@dataclass(frozen=True)
class FileIndexScanSummary:
    root_id: str
    canonical_path: str
    indexed_files: int
    removed_stale: int
    skipped_excluded: int
    skipped_reparse_points: int
    permission_errors: int
    availability: Literal["available", "unavailable"]
    elapsed_ms: float


@dataclass(frozen=True)
class FileSearchResponse:
    query: str
    hits: tuple[FileMetadataHit, ...]
    total_candidates_scanned: int
    active_roots_count: int
    elapsed_ms: float


def _fold_name(raw: str) -> str:
    return unicodedata.normalize("NFKC", raw).strip().casefold()


def _is_excluded_secret_file(filename: str) -> bool:
    folded = filename.casefold()
    if folded in EXCLUDED_SECRET_FILENAMES:
        return True
    if folded.startswith(".env."):
        return True
    ext = Path(folded).suffix
    return ext in EXCLUDED_SECRET_SUFFIXES


def _deterministic_file_id(root_id: str, relative_path: str) -> str:
    norm = relative_path.replace("\\", "/").casefold()
    return hashlib.sha256(f"{root_id}:{norm}".encode()).hexdigest()[:32]


class EntityWorkingSet:
    """Bounded per-session working set mapping recent file search results to ordinal indices."""

    def __init__(self, *, max_sessions: int = 32, max_items_per_session: int = 20) -> None:
        self._max_sessions = max_sessions
        self._max_items = max_items_per_session
        self._lock = threading.RLock()
        self._sessions: OrderedDict[str, tuple[FileMetadataHit, ...]] = OrderedDict()

    def set_results(self, session_id: str, hits: tuple[FileMetadataHit, ...]) -> None:
        with self._lock:
            self._sessions[session_id] = hits[: self._max_items]
            self._sessions.move_to_end(session_id)
            while len(self._sessions) > self._max_sessions:
                self._sessions.popitem(last=False)

    def get_by_index(self, session_id: str, index_1based: int) -> FileMetadataHit | None:
        if index_1based < 1:
            return None
        with self._lock:
            items = self._sessions.get(session_id)
            if not items or index_1based > len(items):
                return None
            return items[index_1based - 1]

    def get_all(self, session_id: str) -> tuple[FileMetadataHit, ...]:
        with self._lock:
            return self._sessions.get(session_id, ())

    def clear_session(self, session_id: str | None = None) -> None:
        with self._lock:
            if session_id is None:
                self._sessions.clear()
            else:
                self._sessions.pop(session_id, None)


class FileIndexService:
    """Manages Layer-1 scoped file metadata indexing, fast exact/fuzzy search, working set & safe open."""

    MAX_FILES_PER_ROOT: int = 50_000

    def __init__(
        self,
        db: DualSqliteManager,
        fs_port: FilesystemSafetyPort,
        clock: ClockPort,
        opener: FileOpenerPort | None = None,
    ) -> None:
        self._db = db
        self._fs = fs_port
        self._clock = clock
        self._opener = opener
        self.working_set = EntityWorkingSet()

    def _get_active_roots_map(self) -> dict[str, tuple[str, int]]:
        """Read active non-revoked, non-tombstoned source_root rows from core.db."""
        with self._db.core_read() as conn:
            rows = conn.execute(
                "SELECT id, canonical_path, revision FROM source_root WHERE enabled = 1 AND revoked_at IS NULL"
            ).fetchall()
            tomb_rows = conn.execute(
                "SELECT entity_id FROM deletion_ledger WHERE entity_type = 'source_root'"
            ).fetchall()
        deleted = {str(r["entity_id"]) for r in tomb_rows}
        result: dict[str, tuple[str, int]] = {}
        for r in rows:
            rid = str(r["id"])
            if rid in deleted:
                continue
            result[rid] = (str(r["canonical_path"]), int(r["revision"]))
        return result

    def scan_authorized_root(self, root_id: str) -> FileIndexScanSummary:
        started = time.perf_counter()
        active_roots = self._get_active_roots_map()
        root_info = active_roots.get(root_id)
        if root_info is None:
            raise FileIndexError(
                ErrorCode.NOT_FOUND, f"Active authorized root '{root_id}' not found."
            )
        canonical_root, root_revision = root_info
        root_path = Path(canonical_root)
        now_iso = self._clock.now_utc().isoformat()

        # External/unplugged drive handling: mark existing rows unavailable cleanly
        if not root_path.is_dir():
            with self._db.knowledge_tx() as conn:
                conn.execute(
                    "UPDATE file_metadata SET availability = 'unavailable', indexed_at = ? WHERE root_id = ?",
                    (now_iso, root_id),
                )
            return FileIndexScanSummary(
                root_id=root_id,
                canonical_path=canonical_root,
                indexed_files=0,
                removed_stale=0,
                skipped_excluded=0,
                skipped_reparse_points=0,
                permission_errors=0,
                availability="unavailable",
                elapsed_ms=round((time.perf_counter() - started) * 1000.0, 2),
            )

        root_insp = self._fs.inspect_path(canonical_root)
        if root_insp.is_reparse_point:
            raise FileIndexError(
                ErrorCode.DENIED, "Authorized root cannot be a symlink/reparse point."
            )

        indexed_rows: list[tuple[object, ...]] = []
        seen_rel_paths: set[str] = set()
        skipped_excluded = 0
        skipped_reparse = 0
        permission_errors = 0

        def _on_walk_error(_exc: OSError) -> None:
            nonlocal permission_errors
            permission_errors += 1

        for dirpath, dirnames, filenames in os.walk(
            canonical_root, topdown=True, followlinks=False, onerror=_on_walk_error
        ):
            cur_dir = Path(dirpath)
            kept_dirs: list[str] = []
            for dname in dirnames:
                if dname.casefold() in EXCLUDED_DIR_NAMES:
                    skipped_excluded += 1
                    continue
                child_dir = cur_dir / dname
                try:
                    if child_dir.is_symlink() or self._fs.inspect_path(str(child_dir)).is_reparse_point:
                        skipped_reparse += 1
                        continue
                except OSError:
                    permission_errors += 1
                    continue
                kept_dirs.append(dname)
            dirnames[:] = kept_dirs

            for fname in filenames:
                if len(indexed_rows) >= self.MAX_FILES_PER_ROOT:
                    break
                if _is_excluded_secret_file(fname):
                    skipped_excluded += 1
                    continue
                fpath = cur_dir / fname
                try:
                    if fpath.is_symlink() or self._fs.inspect_path(str(fpath)).is_reparse_point:
                        skipped_reparse += 1
                        continue
                    st = fpath.stat()
                except OSError:
                    permission_errors += 1
                    continue
                try:
                    rel_posix = fpath.relative_to(root_path).as_posix()
                except ValueError:
                    continue
                seen_rel_paths.add(rel_posix)
                file_id = _deterministic_file_id(root_id, rel_posix)
                indexed_rows.append(
                    (
                        file_id,
                        root_id,
                        root_revision,
                        rel_posix,
                        fname,
                        _fold_name(fname),
                        fpath.suffix.lower(),
                        int(st.st_size),
                        int(st.st_mtime_ns),
                        0,
                        "available",
                        now_iso,
                    )
                )
            if len(indexed_rows) >= self.MAX_FILES_PER_ROOT:
                break

        removed_stale = 0
        with self._db.knowledge_tx() as conn:
            existing_rows = conn.execute(
                "SELECT relative_path FROM file_metadata WHERE root_id = ?",
                (root_id,),
            ).fetchall()
            existing_rels = {str(r["relative_path"]) for r in existing_rows}
            stale_rels = existing_rels - seen_rel_paths
            for rel in stale_rels:
                cur = conn.execute(
                    "DELETE FROM file_metadata WHERE root_id = ? AND relative_path = ?",
                    (root_id, rel),
                )
                removed_stale += cur.rowcount

            if indexed_rows:
                conn.executemany(
                    """
                    INSERT INTO file_metadata(
                        file_id, root_id, root_revision, relative_path, display_name,
                        name_folded, ext, size_bytes, mtime_ns, is_dir, availability, indexed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(root_id, relative_path) DO UPDATE SET
                        file_id = excluded.file_id,
                        root_revision = excluded.root_revision,
                        display_name = excluded.display_name,
                        name_folded = excluded.name_folded,
                        ext = excluded.ext,
                        size_bytes = excluded.size_bytes,
                        mtime_ns = excluded.mtime_ns,
                        is_dir = excluded.is_dir,
                        availability = excluded.availability,
                        indexed_at = excluded.indexed_at
                    """,
                    indexed_rows,
                )

        return FileIndexScanSummary(
            root_id=root_id,
            canonical_path=canonical_root,
            indexed_files=len(indexed_rows),
            removed_stale=removed_stale,
            skipped_excluded=skipped_excluded,
            skipped_reparse_points=skipped_reparse,
            permission_errors=permission_errors,
            availability="available",
            elapsed_ms=round((time.perf_counter() - started) * 1000.0, 2),
        )

    def search_metadata(
        self,
        query: str,
        *,
        ext: str | None = None,
        modified_after_utc: datetime | None = None,
        root_ids: tuple[str, ...] | None = None,
        limit: int = 10,
        session_id: str | None = None,
    ) -> FileSearchResponse:
        started = time.perf_counter()
        active_roots = self._get_active_roots_map()
        if root_ids is not None:
            allowed_set = set(root_ids)
            active_roots = {k: v for k, v in active_roots.items() if k in allowed_set}

        if not active_roots:
            return FileSearchResponse(
                query=query,
                hits=(),
                total_candidates_scanned=0,
                active_roots_count=0,
                elapsed_ms=round((time.perf_counter() - started) * 1000.0, 2),
            )

        norm_ext: str | None = None
        if ext and ext.strip():
            norm_ext = ext.strip().lower()
            if not norm_ext.startswith("."):
                norm_ext = f".{norm_ext}"

        min_mtime_ns: int | None = None
        if modified_after_utc is not None:
            min_mtime_ns = int(modified_after_utc.timestamp() * 1_000_000_000)

        with self._db.knowledge_read() as conn:
            if norm_ext is not None and min_mtime_ns is not None:
                rows = conn.execute(
                    """
                    SELECT file_id, root_id, root_revision, relative_path, display_name,
                           name_folded, ext, size_bytes, mtime_ns, availability
                    FROM file_metadata
                    WHERE ext = ? AND mtime_ns >= ?
                    ORDER BY mtime_ns DESC
                    LIMIT 10000
                    """,
                    (norm_ext, min_mtime_ns),
                ).fetchall()
            elif norm_ext is not None:
                rows = conn.execute(
                    """
                    SELECT file_id, root_id, root_revision, relative_path, display_name,
                           name_folded, ext, size_bytes, mtime_ns, availability
                    FROM file_metadata
                    WHERE ext = ?
                    ORDER BY mtime_ns DESC
                    LIMIT 10000
                    """,
                    (norm_ext,),
                ).fetchall()
            elif min_mtime_ns is not None:
                rows = conn.execute(
                    """
                    SELECT file_id, root_id, root_revision, relative_path, display_name,
                           name_folded, ext, size_bytes, mtime_ns, availability
                    FROM file_metadata
                    WHERE mtime_ns >= ?
                    ORDER BY mtime_ns DESC
                    LIMIT 10000
                    """,
                    (min_mtime_ns,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT file_id, root_id, root_revision, relative_path, display_name,
                           name_folded, ext, size_bytes, mtime_ns, availability
                    FROM file_metadata
                    ORDER BY mtime_ns DESC
                    LIMIT 10000
                    """
                ).fetchall()

        q_fold = _fold_name(query)
        q_tokens = [tok for tok in re.findall(r"[a-z0-9]+", q_fold) if tok]

        scored: list[tuple[float, int, FileMetadataHit]] = []
        scanned = 0

        for row in rows:
            rid = str(row["root_id"])
            root_meta = active_roots.get(rid)
            if root_meta is None:
                continue
            root_path_str, active_rev = root_meta
            if int(row["root_revision"]) != active_rev:
                continue
            scanned += 1
            name_folded = str(row["name_folded"])
            rel_path = str(row["relative_path"])
            display_name = str(row["display_name"])
            file_ext = str(row["ext"])
            mtime_ns = int(row["mtime_ns"])

            if not q_fold:
                score = 1.0
            else:
                score = self._score_filename(q_fold, q_tokens, name_folded, rel_path.casefold())
                if score < 0.56:
                    continue

            avail_raw = str(row["availability"])
            avail: Literal["available", "unavailable"] = (
                "available" if avail_raw == "available" else "unavailable"
            )
            scored.append(
                (
                    score,
                    mtime_ns,
                    FileMetadataHit(
                        file_id=str(row["file_id"]),
                        root_id=rid,
                        root_path=root_path_str,
                        relative_path=rel_path,
                        display_name=display_name,
                        ext=file_ext,
                        size_bytes=int(row["size_bytes"]),
                        mtime_ns=mtime_ns,
                        availability=avail,
                        score=round(score, 4),
                    ),
                )
            )

        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        bounded_limit = max(1, min(limit, 50))
        top_candidates = [item[2] for item in scored[: bounded_limit * 2]]

        # Honest freshness verification on top hits: detect externally deleted/stale files
        verified_hits: list[FileMetadataHit] = []
        stale_file_ids: list[str] = []
        for hit in top_candidates:
            disk_path = Path(hit.root_path) / hit.relative_path
            exists_now = disk_path.is_file()
            if not exists_now:
                stale_file_ids.append(hit.file_id)
                verified_hits.append(
                    FileMetadataHit(
                        file_id=hit.file_id,
                        root_id=hit.root_id,
                        root_path=hit.root_path,
                        relative_path=hit.relative_path,
                        display_name=hit.display_name,
                        ext=hit.ext,
                        size_bytes=hit.size_bytes,
                        mtime_ns=hit.mtime_ns,
                        availability="unavailable",
                        score=hit.score,
                    )
                )
            else:
                verified_hits.append(hit)
            if len(verified_hits) >= bounded_limit:
                break

        if stale_file_ids:
            with self._db.knowledge_tx() as conn:
                for fid in stale_file_ids:
                    conn.execute(
                        "UPDATE file_metadata SET availability = 'unavailable' WHERE file_id = ?",
                        (fid,),
                    )

        # Put live available files ahead of unavailable stale entries while preserving relative rank
        verified_hits.sort(
            key=lambda h: (1 if h.availability == "available" else 0, h.score, h.mtime_ns),
            reverse=True,
        )
        final_tuple = tuple(verified_hits[:bounded_limit])

        if session_id:
            self.working_set.set_results(session_id, final_tuple)

        return FileSearchResponse(
            query=query,
            hits=final_tuple,
            total_candidates_scanned=scanned,
            active_roots_count=len(active_roots),
            elapsed_ms=round((time.perf_counter() - started) * 1000.0, 2),
        )

    def resolve_working_set_index(
        self, session_id: str, index_1based: int
    ) -> FileMetadataHit | None:
        return self.working_set.get_by_index(session_id, index_1based)

    def open_file(self, hit: FileMetadataHit) -> FileOpenReceipt:
        active_roots = self._get_active_roots_map()
        root_meta = active_roots.get(hit.root_id)
        if root_meta is None:
            return FileOpenReceipt(
                opened=False,
                canonical_path="",
                verification_kind="prohibited",
                detail="Root directory is no longer authorized or has been revoked.",
            )
        authorized_root, _rev = root_meta

        if not is_safe_document_open_extension(hit.ext):
            return FileOpenReceipt(
                opened=False,
                canonical_path=str(Path(authorized_root) / hit.relative_path),
                verification_kind="prohibited",
                detail=f"File '{hit.display_name}' memiliki ekstensi '{hit.ext or '(tanpa ekstensi)'}' yang dilarang dibuka otomatis.",
            )

        try:
            canonical_path = self._fs.resolve_within_root(authorized_root, hit.relative_path)
        except PermissionError as exc:
            return FileOpenReceipt(
                opened=False,
                canonical_path="",
                verification_kind="prohibited",
                detail=str(exc),
            )

        insp = self._fs.inspect_path(canonical_path)
        if insp.is_reparse_point:
            return FileOpenReceipt(
                opened=False,
                canonical_path=canonical_path,
                verification_kind="prohibited",
                detail="File symlink/reparse point ditolak oleh kebijakan keamanan.",
            )
        if not Path(canonical_path).is_file():
            return FileOpenReceipt(
                opened=False,
                canonical_path=canonical_path,
                verification_kind="not_found",
                detail=f"File '{hit.display_name}' tidak lagi ditemukan di disk (indeks usang).",
            )

        if self._opener is None:
            return FileOpenReceipt(
                opened=False,
                canonical_path=canonical_path,
                verification_kind="disabled",
                detail="File opener adapter is not wired.",
            )
        return self._opener.open_registered_file(
            canonical_path, authorized_root=authorized_root
        )

    @staticmethod
    def _score_filename(
        q_fold: str, q_tokens: list[str], name_folded: str, rel_folded: str
    ) -> float:
        stem = Path(name_folded).stem
        if q_fold in (name_folded, stem):
            return 1.0
        if name_folded.startswith(q_fold):
            return 0.94
        if q_fold in name_folded:
            return 0.90
        if q_tokens and all(tok in name_folded for tok in q_tokens):
            return 0.87
        if q_tokens and all(tok in rel_folded for tok in q_tokens):
            return 0.80

        seq_name = difflib.SequenceMatcher(None, q_fold, name_folded).ratio()
        seq_stem = difflib.SequenceMatcher(None, q_fold, stem).ratio()
        best = max(seq_name, seq_stem)

        if q_tokens:
            name_tokens = set(re.findall(r"[a-z0-9]+", name_folded))
            rel_tokens = set(re.findall(r"[a-z0-9]+", rel_folded))
            if name_tokens:
                # Per-token fuzzy recall handles typos like "laporn" -> "laporan"
                token_scores = [
                    max(difflib.SequenceMatcher(None, qt, nt).ratio() for nt in name_tokens)
                    for qt in q_tokens
                ]
                avg_tok = sum(token_scores) / len(token_scores)
                best = max(best, avg_tok * 0.89)
            if rel_tokens:
                overlap = len(set(q_tokens) & rel_tokens) / len(q_tokens)
                best = max(best, overlap * 0.78)
        return best
