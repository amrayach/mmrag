-- Reverse 021_rag_hybrid_lexical_up.sql.

DROP INDEX IF EXISTS idx_rag_chunks_content_tsv;

ALTER TABLE rag_chunks
  DROP COLUMN IF EXISTS content_tsv;
