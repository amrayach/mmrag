-- Hybrid retrieval prep: lexical search column + GIN index.
-- German text search config (project corpus is primarily German).
-- Idempotent: safe to re-run.

ALTER TABLE rag_chunks
  ADD COLUMN IF NOT EXISTS content_tsv tsvector
  GENERATED ALWAYS AS (
    to_tsvector(
      'german',
      coalesce(content_text, '') || ' ' || coalesce(caption, '')
    )
  ) STORED;

CREATE INDEX IF NOT EXISTS idx_rag_chunks_content_tsv
  ON rag_chunks USING GIN (content_tsv);
