import os

import requests

from app import main


def test_ollama_embed_batch_splits_failed_batches_and_isolates_bad_chunk(monkeypatch):
    calls = []

    def fake_retry(fn, max_retries=3, backoff=(2, 4, 8)):
        return fn()

    def fake_post(url, json, timeout):
        inputs = list(json["input"])
        calls.append(inputs)

        class Response:
            def raise_for_status(self):
                if len(inputs) > 1 or inputs[0] == "bad":
                    raise requests.HTTPError("embed failed")

            def json(self):
                return {"embeddings": [[float(len(inputs[0]))] * 1024]}

        return Response()

    monkeypatch.setattr(main, "_retry", fake_retry)
    monkeypatch.setattr(main.requests, "post", fake_post)

    embeddings = main.ollama_embed_batch(["ok1", "bad", "ok2"])

    assert embeddings[0] == [3.0] * 1024
    assert embeddings[1] is None
    assert embeddings[2] == [3.0] * 1024
    assert ["ok1", "bad", "ok2"] in calls
    assert ["bad"] in calls


def test_ollama_embed_batch_cleans_replacement_characters_before_embedding(monkeypatch):
    calls = []

    def fake_retry(fn, max_retries=3, backoff=(2, 4, 8)):
        return fn()

    def fake_post(url, json, timeout):
        inputs = list(json["input"])
        calls.append(inputs)

        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {"embeddings": [[1.0] * 1024 for _ in inputs]}

        return Response()

    monkeypatch.setattr(main, "_retry", fake_retry)
    monkeypatch.setattr(main.requests, "post", fake_post)

    noisy = "BMW Group Bericht " + ("\ufffd" * 80) + " Umsatz 2023"
    embeddings = main.ollama_embed_batch(["normal text", noisy, "more normal text"])

    assert embeddings[0] == [1.0] * 1024
    assert embeddings[1] == [1.0] * 1024
    assert embeddings[2] == [1.0] * 1024
    assert calls == [["normal text", "BMW Group Bericht Umsatz 2023", "more normal text"]]


def test_ollama_embed_batch_skips_replacement_character_only_garbage(monkeypatch):
    calls = []

    def fake_retry(fn, max_retries=3, backoff=(2, 4, 8)):
        return fn()

    def fake_post(url, json, timeout):
        calls.append(list(json["input"]))
        raise AssertionError("garbage-only input should not call Ollama")

    monkeypatch.setattr(main, "_retry", fake_retry)
    monkeypatch.setattr(main.requests, "post", fake_post)

    embeddings = main.ollama_embed_batch(["\ufffd" * 120])

    assert embeddings == [None]
    assert calls == []


def test_submit_pdf_deduplicates_active_paths(monkeypatch, tmp_path):
    submitted = []

    class FakeExecutor:
        def submit(self, fn, path, lang):
            submitted.append((fn, path, lang))

    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")

    monkeypatch.setattr(main, "doc_executor", FakeExecutor())
    with main._submit_lock:
        main._submitted_paths.clear()

    assert main._submit_pdf(str(pdf), "de") is True
    assert main._submit_pdf(str(pdf), "de") is False
    assert len(submitted) == 1
    assert submitted[0][1] == os.path.abspath(str(pdf))

    with main._submit_lock:
        main._submitted_paths.clear()
