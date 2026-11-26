-- J.A.R.V.I.S. Knowledge Index Database Initial Schema (v0.2.1)
-- Derived & rebuildable index store (jarvis_knowledge.db)
-- Never joined directly with jarvis_core.db; every query filters against core.db source_root + deletion_ledger.

CREATE TABLE IF NOT EXISTS document (
    id TEXT PRIMARY KEY,
    root_id TEXT NOT NULL,
    root_revision INTEGER NOT NULL CHECK (root_revision >= 1),
    relative_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    byte_size INTEGER NOT NULL CHECK (byte_size >= 0),
    mtime_ns INTEGER NOT NULL,
    mime_type TEXT NOT NULL,
    index_state TEXT NOT NULL CHECK (index_state IN ('indexed', 'ocr_required', 'unsupported', 'failed')),
    source_revision INTEGER NOT NULL DEFAULT 1 CHECK (source_revision >= 1),
    UNIQUE(root_id, relative_path)
);

CREATE INDEX IF NOT EXISTS idx_document_root_id ON document(root_id);

CREATE TABLE IF NOT EXISTS chunk (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    root_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    locator_json TEXT NOT NULL,
    text TEXT NOT NULL,
    token_count INTEGER NOT NULL CHECK (token_count >= 0),
    source_revision INTEGER NOT NULL DEFAULT 1 CHECK (source_revision >= 1),
    UNIQUE(document_id, source_revision, ordinal)
);

CREATE INDEX IF NOT EXISTS idx_chunk_root_id ON chunk(root_id);
CREATE INDEX IF NOT EXISTS idx_chunk_document_id ON chunk(document_id);

CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(
    chunk_id UNINDEXED,
    root_id UNINDEXED,
    text,
    tokenize='unicode61'
);

CREATE TRIGGER IF NOT EXISTS trg_chunk_ai AFTER INSERT ON chunk BEGIN
    INSERT INTO chunk_fts(chunk_id, root_id, text) VALUES (new.id, new.root_id, new.text);
END;

CREATE TRIGGER IF NOT EXISTS trg_chunk_ad AFTER DELETE ON chunk BEGIN
    DELETE FROM chunk_fts WHERE chunk_id = old.id;
END;

CREATE TRIGGER IF NOT EXISTS trg_chunk_au AFTER UPDATE OF text, root_id ON chunk BEGIN
    DELETE FROM chunk_fts WHERE chunk_id = old.id;
    INSERT INTO chunk_fts(chunk_id, root_id, text) VALUES (new.id, new.root_id, new.text);
END;

CREATE TABLE IF NOT EXISTS embedding_index_generation (
    id TEXT PRIMARY KEY,
    embedding_space_id TEXT NOT NULL,
    dimension INTEGER NOT NULL CHECK (dimension > 0),
    status TEXT NOT NULL CHECK (status IN ('building', 'ready', 'active', 'superseded', 'failed')),
    is_active_pointer INTEGER NOT NULL DEFAULT 0 CHECK (is_active_pointer IN (0, 1)),
    created_at TEXT NOT NULL,
    promoted_at TEXT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_embedding_generation_active
    ON embedding_index_generation(is_active_pointer) WHERE is_active_pointer = 1;

CREATE TABLE IF NOT EXISTS chunk_embedding (
    generation_id TEXT NOT NULL REFERENCES embedding_index_generation(id) ON DELETE CASCADE,
    chunk_id TEXT NOT NULL REFERENCES chunk(id) ON DELETE CASCADE,
    vector_blob BLOB NOT NULL,
    PRIMARY KEY (generation_id, chunk_id)
);
