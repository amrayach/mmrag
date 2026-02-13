\connect rag

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS rag_docs (
  doc_id UUID PRIMARY KEY,
  filename TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  lang TEXT NOT NULL DEFAULT 'de',
  pages INT NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS rag_chunks (
  id BIGSERIAL PRIMARY KEY,
  doc_id UUID NOT NULL REFERENCES rag_docs(doc_id) ON DELETE CASCADE,
  chunk_type TEXT NOT NULL,         -- 'text' | 'image'
  page INT NOT NULL DEFAULT 0,
  content_text TEXT,
  caption TEXT,
  asset_path TEXT,
  embedding VECTOR(768),
  meta JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_rag_chunks_doc_page ON rag_chunks(doc_id, page);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_type ON rag_chunks(chunk_type);

DO $$
BEGIN
  EXECUTE 'CREATE INDEX IF NOT EXISTS idx_rag_chunks_embedding_hnsw ON rag_chunks USING hnsw (embedding vector_cosine_ops);';
EXCEPTION WHEN others THEN
END $$;
