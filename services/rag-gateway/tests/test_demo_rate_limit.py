from types import SimpleNamespace

from app import main


def _reset_rate_limit(monkeypatch, enabled=True, limit=10):
    monkeypatch.setattr(main, "RAG_DEMO_RATE_LIMIT_ENABLED", enabled)
    monkeypatch.setattr(main, "RAG_DEMO_MAX_QUERIES_PER_HOUR", limit)
    with main._DEMO_RATE_LIMIT_LOCK:
        main._DEMO_RATE_LIMIT_STATE.clear()


def test_demo_reviewer_id_uses_header_priority():
    request = SimpleNamespace(
        headers={
            "X-OpenWebUI-User-Email": "openwebui@example.invalid",
            "X-Demo-Email": "demo@example.invalid",
            "X-Forwarded-User": "forwarded@example.invalid",
        },
        client=SimpleNamespace(host="127.0.0.1"),
    )

    assert main.demo_reviewer_id(request) == "openwebui@example.invalid"


def test_demo_reviewer_id_falls_back_to_anonymous_client_host():
    request = SimpleNamespace(headers={}, client=SimpleNamespace(host="127.0.0.1"))

    assert main.demo_reviewer_id(request) == "anonymous:127.0.0.1"


def test_disabled_flag_preserves_allow_behavior(monkeypatch):
    _reset_rate_limit(monkeypatch, enabled=False, limit=10)

    for i in range(20):
        result = main.check_demo_rate_limit("reviewer@example.invalid", now=1000 + i)
        assert result.allowed is True
        assert result.remaining is None

    assert main._DEMO_RATE_LIMIT_STATE == {}


def test_eleventh_request_for_same_reviewer_is_blocked(monkeypatch):
    _reset_rate_limit(monkeypatch, enabled=True, limit=10)

    for i in range(10):
        result = main.check_demo_rate_limit("reviewer@example.invalid", now=1000 + i)
        assert result.allowed is True
        assert result.remaining == 9 - i

    blocked = main.check_demo_rate_limit("reviewer@example.invalid", now=1010)
    assert blocked.allowed is False
    assert blocked.remaining == 0
    assert blocked.retry_after is not None
    assert blocked.retry_after > 0


def test_separate_reviewers_have_separate_counters(monkeypatch):
    _reset_rate_limit(monkeypatch, enabled=True, limit=10)

    for i in range(10):
        assert main.check_demo_rate_limit("a@example.invalid", now=2000 + i).allowed is True

    assert main.check_demo_rate_limit("a@example.invalid", now=2010).allowed is False
    assert main.check_demo_rate_limit("b@example.invalid", now=2010).allowed is True


def test_stream_blocked_generator_includes_done():
    result = main.DemoRateLimitResult(
        allowed=False,
        remaining=0,
        retry_after=120,
        limit=10,
    )

    chunks = list(
        main.sse_rate_limit_error_generator(
            "chatcmpl-test",
            "gemma4:26b",
            1234,
            result,
        )
    )

    assert "Demo-Limit" in "".join(chunks)
    assert chunks[-1] == "data: [DONE]\n\n"
