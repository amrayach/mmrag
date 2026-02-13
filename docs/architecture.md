# Architecture (Scenario A)

Chat:
OpenWebUI (UI) -> rag-gateway (OpenAI-compatible) -> n8n (Chat Brain) -> Postgres(pgvector) + Ollama

Ingestion:
FileBrowser upload -> data/inbox -> n8n (Ingestion Factory) -> pdf-ingest -> Postgres(pgvector) + assets (nginx)
