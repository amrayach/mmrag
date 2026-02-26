.PHONY: up down restart logs health models reset build prewarm ingest rss-ingest rss-logs test-rag

up:
	docker compose up -d

down:
	docker compose down

build:
	docker compose build --no-cache pdf-ingest rag-gateway rss-ingest

restart:
	docker compose restart

logs:
	docker compose logs -f --tail=50

health:
	bash scripts/health_check.sh

models:
	bash scripts/setup_models.sh

reset:
	bash reset_demo.sh

prewarm:
	bash scripts/prewarm.sh

ingest:
	curl -s -X POST http://127.0.0.1:56150/webhook/ingest-now | python3 -m json.tool

rss-ingest:
	curl -s -X POST http://127.0.0.1:56150/webhook/rss-ingest-now | python3 -m json.tool

rss-logs:
	docker compose logs -f --tail=50 rss-ingest

test-rag:
	@echo "Sending test query to RAG gateway..."
	curl -s -X POST http://127.0.0.1:56151/v1/chat/completions \
		-H 'Content-Type: application/json' \
		-d '{"messages":[{"role":"user","content":"Was steht in den Dokumenten?"}]}' \
		| python3 -m json.tool
