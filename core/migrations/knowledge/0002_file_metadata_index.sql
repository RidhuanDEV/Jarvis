-- Layer-1 Scoped Filesystem Metadata Index (Stage G2 / B10, DEC-032)
-- Derived rebuildable metadata index strictly filtered against core.db source_root & deletion_ledger.

CREATE TABLE IF NOT EXISTS file_metadata (
    file_id TEXT PRIMARY KEY,
    root_id TEXT NOT NULL,
    root_revision INTEGER NOT NULL,
    relative_path TEXT NOT NULL,
    display_name TEXT NOT NULL,
    name_folded TEXT NOT NULL,
    ext TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL,
    is_dir INTEGER NOT NULL DEFAULT 0,
    availability TEXT NOT NULL DEFAULT 'available',
    indexed_at TEXT NOT NULL,
    UNIQUE(root_id, relative_path)
);

CREATE INDEX IF NOT EXISTS idx_file_metadata_root ON file_metadata(root_id, root_revision);
CREATE INDEX IF NOT EXISTS idx_file_metadata_name ON file_metadata(name_folded);
CREATE INDEX IF NOT EXISTS idx_file_metadata_ext ON file_metadata(ext);
CREATE INDEX IF NOT EXISTS idx_file_metadata_mtime ON file_metadata(mtime_ns DESC);
