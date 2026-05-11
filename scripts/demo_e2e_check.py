#!/usr/bin/env python3
"""End-to-end local health check for the mmrag demo.

This script is deliberately host-side and diagnostic-only:
- no Docker state changes (only read-only ``docker compose ps``, ``exec`` and
  ``port`` calls);
- no DB writes;
- no external network calls;
- no service/retrieval/model changes.

RAG source detection note:
``rag-gateway`` returns OpenAI-compatible non-stream responses. In this project
the final sources/images are appended to ``choices[0].message.content`` as a
Markdown suffix. The smoke check therefore counts non-image Markdown HTTP links
in that content, and also supports explicit ``sources`` fields if a future
response shape adds one.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
HEALTH_DIR = ROOT / "data" / "eval" / "demo_health"
HISTORY_DIR = HEALTH_DIR / "history"
LATEST_JSON = HEALTH_DIR / "latest.json"
LATEST_MD = HEALTH_DIR / "latest.md"
GOLDEN_QUERY = HEALTH_DIR / "golden_query.json"
PROMPTS_JSON = ROOT / "data" / "eval" / "prompts.json"
TRACE_DIR = ROOT / "data" / "rag-traces"

REQUIRED_SERVICES = ("rag-gateway", "postgres", "ollama")
OPTIONAL_SERVICES = (
    "openwebui",
    "pdf-ingest",
    "rss-ingest",
    "n8n",
    "adminer",
    "filebrowser",
    "assets",
)


@dataclass
class CheckResult:
    status: str
    required: bool
    latency_ms: int
    details: dict[str, Any]
    reason: str | None = None


def now_local() -> datetime:
    return datetime.now().astimezone()


def iso_now() -> str:
    return now_local().isoformat(timespec="seconds")


def history_stamp(ts: datetime) -> str:
    return ts.strftime("%Y%m%dT%H%M%S")


def elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    path = ROOT / ".env"
    if not path.exists():
        return env
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip("'\"")
        env[key.strip()] = value
    return env


def env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def active_model(env: dict[str, str]) -> str:
    return (
        os.environ.get("DEMO_HEALTH_MODEL")
        or env.get("DEFAULT_MODEL")
        or env.get("OLLAMA_TEXT_MODEL")
        or "gemma4:26b"
    )


def compose_project_name(env: dict[str, str]) -> str:
    if env.get("COMPOSE_PROJECT_NAME"):
        return env["COMPOSE_PROJECT_NAME"]
    compose = ROOT / "docker-compose.yml"
    if compose.exists():
        for line in compose.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^\s*name:\s*['\"]?([^'\"]+)['\"]?\s*$", line)
            if m:
                return m.group(1)
    return "ammer-mmragv2"


def run_cmd(
    args: list[str],
    timeout: float,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=ROOT,
        text=True,
        input=input_text,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def http_json(
    url: str,
    payload: dict[str, Any] | None = None,
    timeout: float = 10,
) -> tuple[int, dict[str, Any], int]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"} if payload is not None else {}
    req = urllib.request.Request(url, data=data, headers=headers)
    start = time.perf_counter()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read()
        status = int(resp.status)
    latency = elapsed_ms(start)
    return status, json.loads(body.decode("utf-8")), latency


def http_get_status(url: str, timeout: float = 5) -> tuple[int, int]:
    start = time.perf_counter()
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        resp.read(256)
        return int(resp.status), elapsed_ms(start)


def atomic_write(path: Path, content: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def read_previous_last_pass() -> str | None:
    try:
        data = json.loads(LATEST_JSON.read_text(encoding="utf-8"))
        value = data.get("last_pass_ts")
        return value if isinstance(value, str) else None
    except Exception:
        return None


def result(
    status: str,
    required: bool,
    start: float,
    details: dict[str, Any] | None = None,
    reason: str | None = None,
) -> CheckResult:
    return CheckResult(status, required, elapsed_ms(start), details or {}, reason)


def normalize_model_name(name: str) -> set[str]:
    if ":" in name:
        base = name.split(":", 1)[0]
        return {name, base}
    return {name, f"{name}:latest"}


def load_golden_query(model: str) -> dict[str, Any]:
    if GOLDEN_QUERY.exists():
        data = json.loads(GOLDEN_QUERY.read_text(encoding="utf-8"))
    else:
        prompts = json.loads(PROMPTS_JSON.read_text(encoding="utf-8"))
        p01 = next(p for p in prompts.get("prompts", []) if p.get("id") == "p01_bmw_kennzahlen")
        data = {
            "_rationale": "fallback generated from prompts.json p01",
            "prompt_id": "p01",
            "query_id": "p01",
            "source_prompt_id": "p01_bmw_kennzahlen",
            "query": p01["turns"][0]["user"],
            "expected_min_sources": 1,
            "expected_max_latency_ms": 30000,
            "model": model,
        }
    if os.environ.get("DEMO_HEALTH_QUERY"):
        data = dict(data)
        data["query"] = os.environ["DEMO_HEALTH_QUERY"]
        data["prompt_id"] = "env_override"
        data["query_id"] = "env_override"
    data["model"] = model
    return data


def gateway_url_from_compose(timeout: float) -> str:
    override = os.environ.get("DEMO_HEALTH_GATEWAY_URL")
    if override:
        return override.rstrip("/")
    cp = run_cmd(["docker", "compose", "port", "rag-gateway", "8000"], timeout)
    if cp.returncode == 0 and cp.stdout.strip():
        host_port = cp.stdout.strip().splitlines()[-1]
        if ":" in host_port:
            host, port = host_port.rsplit(":", 1)
            if host in {"0.0.0.0", "::"}:
                host = "127.0.0.1"
            return f"http://{host}:{port}"
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    in_gateway = False
    for raw in compose.splitlines():
        if re.match(r"^\s{2}rag-gateway:\s*$", raw):
            in_gateway = True
            continue
        if in_gateway and re.match(r"^\s{2}[A-Za-z0-9_-]+:\s*$", raw):
            break
        if in_gateway:
            m = re.search(r"127\.0\.0\.1:(\d+):8000", raw)
            if m:
                return f"http://127.0.0.1:{m.group(1)}"
    return "http://127.0.0.1:56155"


def compose_port(service: str, target_port: str, timeout: float) -> str | None:
    cp = run_cmd(["docker", "compose", "port", service, target_port], timeout)
    if cp.returncode != 0 or not cp.stdout.strip():
        return None
    host_port = cp.stdout.strip().splitlines()[-1]
    if ":" not in host_port:
        return None
    host, port = host_port.rsplit(":", 1)
    if host in {"0.0.0.0", "::"}:
        host = "127.0.0.1"
    return f"http://{host}:{port}"


def parse_compose_ps(raw: str) -> list[dict[str, Any]]:
    raw = raw.strip()
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [x for x in parsed if isinstance(x, dict)]
        if isinstance(parsed, dict):
            return [parsed]
    except json.JSONDecodeError:
        pass
    rows: list[dict[str, Any]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def check_disk_space(min_gb: float) -> CheckResult:
    start = time.perf_counter()
    stat = os.statvfs("/srv")
    free_gb = (stat.f_bavail * stat.f_frsize) / (1024**3)
    status = "PASS" if free_gb > min_gb else "FAIL"
    reason = None if status == "PASS" else f"/srv free space {free_gb:.1f} GB <= {min_gb:.1f} GB"
    return result(status, True, start, {"path": "/srv", "free_gb": round(free_gb, 2), "min_gb": min_gb}, reason)


def check_compose_services(timeout: float, project: str) -> CheckResult:
    start = time.perf_counter()
    cp = run_cmd(["docker", "compose", "ps", "--format", "json"], timeout)
    if cp.returncode != 0:
        return result("FAIL", True, start, {"project": project}, "docker compose ps failed")
    try:
        rows = parse_compose_ps(cp.stdout)
    except Exception as exc:
        return result("FAIL", True, start, {"project": project}, f"failed to parse compose ps JSON: {exc}")
    by_service = {str(r.get("Service") or r.get("Name") or ""): r for r in rows}
    required_running: list[str] = []
    required_unhealthy: list[str] = []
    optional_running: list[str] = []
    optional_not_running: list[str] = []
    service_details: dict[str, Any] = {}
    for svc in (*REQUIRED_SERVICES, *OPTIONAL_SERVICES):
        row = by_service.get(svc)
        state = str((row or {}).get("State") or "").lower()
        health = str((row or {}).get("Health") or "").lower()
        service_details[svc] = {"state": state or "missing", "health": health or None}
        running = state == "running"
        healthy = health in {"", "healthy"}
        if svc in REQUIRED_SERVICES:
            if running and healthy:
                required_running.append(svc)
            else:
                required_unhealthy.append(svc)
        else:
            if running:
                optional_running.append(svc)
            else:
                optional_not_running.append(svc)
    if required_unhealthy:
        return result(
            "FAIL",
            True,
            start,
            {
                "project": project,
                "required_running": required_running,
                "required_failed": required_unhealthy,
                "optional_running": optional_running,
                "optional_not_running": optional_not_running,
                "services": service_details,
            },
            f"required compose services not running/healthy: {', '.join(required_unhealthy)}",
        )
    return result(
        "PASS",
        True,
        start,
        {
            "project": project,
            "required_running": required_running,
            "optional_running": optional_running,
            "optional_not_running": optional_not_running,
            "services": service_details,
        },
    )


def check_health_endpoints(gateway_url: str, timeout: float, env: dict[str, str]) -> CheckResult:
    start = time.perf_counter()
    details: dict[str, Any] = {"gateway_url": gateway_url}
    try:
        code, gateway_latency = http_get_status(f"{gateway_url}/health", timeout=min(5, timeout))
        details["rag_gateway"] = {"status_code": code, "latency_ms": gateway_latency}
        if code != 200:
            return result("FAIL", True, start, details, f"rag-gateway /health returned HTTP {code}")
    except Exception as exc:
        details["rag_gateway"] = {"error": type(exc).__name__}
        return result("FAIL", True, start, details, f"rag-gateway /health failed: {type(exc).__name__}")
    db = env.get("RAG_DB") or "rag"
    user = env.get("POSTGRES_USER") or "rag_user"
    sql = "SELECT 1; SELECT COUNT(*) FROM rag_docs; SELECT COUNT(*) FROM rag_chunks;"
    cp = run_cmd(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "postgres",
            "psql",
            "-h",
            "127.0.0.1",
            "-U",
            user,
            "-d",
            db,
            "-tA",
            "-c",
            sql,
        ],
        timeout=min(10, timeout),
    )
    rows = [line.strip() for line in cp.stdout.splitlines() if line.strip()]
    details["postgres"] = {
        "select_1_ok": cp.returncode == 0 and bool(rows) and rows[0] == "1",
        "rag_docs_count": int(rows[1]) if len(rows) > 1 and rows[1].isdigit() else None,
        "rag_chunks_count": int(rows[2]) if len(rows) > 2 and rows[2].isdigit() else None,
    }
    if cp.returncode != 0 or len(rows) < 3 or rows[0] != "1":
        return result("FAIL", True, start, details, "postgres read-only SQL probe failed")
    openwebui_url = compose_port("openwebui", "8080", min(5, timeout))
    if openwebui_url:
        try:
            code, latency = http_get_status(f"{openwebui_url}/", timeout=min(5, timeout))
            details["openwebui"] = {"status": "PASS" if code == 200 else "WARN", "status_code": code, "latency_ms": latency}
        except Exception as exc:
            details["openwebui"] = {"status": "WARN", "error": type(exc).__name__}
    else:
        details["openwebui"] = {"status": "SKIP", "reason": "port not available"}
    return result("PASS", True, start, details)


def ollama_wget(path: str, timeout: float, payload: dict[str, Any] | None = None) -> tuple[int, str]:
    url = f"http://localhost:11434{path}"
    if payload is None:
        args = ["docker", "compose", "exec", "-T", "ollama", "wget", "-q", "-O-", url]
    else:
        args = [
            "docker",
            "compose",
            "exec",
            "-T",
            "ollama",
            "wget",
            "-q",
            "-O-",
            "--header=Content-Type: application/json",
            "--post-data",
            json.dumps(payload),
            url,
        ]
    cp = run_cmd(args, timeout=timeout)
    return cp.returncode, cp.stdout


def compose_container_ip(service: str, timeout: float) -> str | None:
    cp = run_cmd(["docker", "compose", "ps", "-q", service], timeout=timeout)
    container_id = cp.stdout.strip().splitlines()[0] if cp.returncode == 0 and cp.stdout.strip() else ""
    if not container_id:
        return None
    cp = run_cmd(["docker", "inspect", container_id], timeout=timeout)
    if cp.returncode != 0 or not cp.stdout.strip():
        return None
    try:
        inspected = json.loads(cp.stdout)
        networks = inspected[0]["NetworkSettings"]["Networks"]
    except (json.JSONDecodeError, KeyError, IndexError, TypeError):
        return None
    if not isinstance(networks, dict):
        return None

    project = compose_project_name(load_env())
    preferred = f"{project}_default"
    preferred_names = [preferred]
    preferred_names.extend(
        name for name in sorted(networks) if name.startswith(f"{project}_")
    )
    preferred_names.extend(sorted(networks))

    seen: set[str] = set()
    for name in preferred_names:
        if name in seen:
            continue
        seen.add(name)
        net = networks.get(name)
        if not isinstance(net, dict):
            continue
        ip = str(net.get("IPAddress") or "").strip()
        if ip:
            return ip
    return None


def ollama_request(path: str, timeout: float, payload: dict[str, Any] | None = None) -> tuple[str, dict[str, Any] | None, str | None]:
    code, stdout = ollama_wget(path, min(10, timeout), payload=payload)
    if code == 0:
        try:
            return "docker_compose_exec_wget", json.loads(stdout), None
        except json.JSONDecodeError:
            return "docker_compose_exec_wget", None, "invalid JSON from Ollama wget response"

    # The current Ollama image may not include wget/curl. The allowed fallback
    # is to dynamically inspect the project Ollama container IP and call it from
    # the host. The IP is never written to reports.
    ip = compose_container_ip("ollama", min(5, timeout))
    if not ip:
        return "docker_inspect_container_ip_http", None, "could not resolve project Ollama container IP"
    try:
        status_code, data, _ = http_json(f"http://{ip}:11434{path}", payload, timeout=min(10, timeout))
    except Exception as exc:
        return "docker_inspect_container_ip_http", None, f"project Ollama HTTP failed: {type(exc).__name__}"
    if status_code != 200:
        return "docker_inspect_container_ip_http", None, f"project Ollama returned HTTP {status_code}"
    return "docker_inspect_container_ip_http", data, None


def check_ollama_models(model: str, timeout: float) -> CheckResult:
    start = time.perf_counter()
    method, data, err = ollama_request("/api/tags", min(10, timeout))
    if err or data is None:
        return result("FAIL", True, start, {"method": method}, f"project Ollama /api/tags failed: {err}")
    names: set[str] = set()
    for item in data.get("models", []):
        if isinstance(item, dict):
            for key in ("name", "model"):
                value = item.get(key)
                if isinstance(value, str):
                    names.add(value)
    embed_ok = bool(names & normalize_model_name("bge-m3"))
    model_ok = bool(names & normalize_model_name(model))
    details = {
        "method": method,
        "bge_m3_available": embed_ok,
        "generation_model_available": model_ok,
        "generation_model": model,
        "available_model_count": len(names),
    }
    if not embed_ok:
        return result("FAIL", True, start, details, "bge-m3 model is not available in project Ollama")
    if not model_ok:
        return result("FAIL", True, start, details, f"generation model {model} is not available in project Ollama")
    return result("PASS", True, start, details)


def check_embedding_spot(timeout: float) -> CheckResult:
    start = time.perf_counter()
    payload = {"model": "bge-m3", "input": ["Demo health check probe"]}
    method, data, err = ollama_request("/api/embed", min(5, timeout), payload=payload)
    if err or data is None:
        return result("FAIL", True, start, {"method": method}, f"project Ollama /api/embed failed: {err}")
    vec = None
    if isinstance(data.get("embeddings"), list) and data["embeddings"]:
        vec = data["embeddings"][0]
    elif isinstance(data.get("embedding"), list):
        vec = data["embedding"]
    if not isinstance(vec, list):
        return result("FAIL", True, start, {"method": method}, "embedding vector missing")
    numeric = all(isinstance(x, (int, float)) for x in vec)
    non_zero = numeric and any(abs(float(x)) > 1e-12 for x in vec)
    dims = len(vec)
    details = {"method": method, "dims": dims, "numeric": numeric, "non_zero": non_zero}
    if dims != 1024 or not numeric or not non_zero:
        return result("FAIL", True, start, details, "embedding vector shape/content check failed")
    return result("PASS", True, start, details)


def check_trace_dir() -> CheckResult:
    start = time.perf_counter()
    try:
        TRACE_DIR.mkdir(parents=True, exist_ok=True)
        test_path = TRACE_DIR / ".health_write_test"
        test_path.write_text("ok\n", encoding="utf-8")
        exists = test_path.exists()
        test_path.unlink()
    except Exception as exc:
        return result("FAIL", True, start, {"path": str(TRACE_DIR.relative_to(ROOT))}, f"trace directory write test failed: {type(exc).__name__}")
    if not exists:
        return result("FAIL", True, start, {"path": str(TRACE_DIR.relative_to(ROOT))}, "trace test file was not created")
    return result("PASS", True, start, {"path": str(TRACE_DIR.relative_to(ROOT))})


def count_sources(response: dict[str, Any], content: str) -> int:
    explicit = 0
    for key in ("sources", "source_documents"):
        value = response.get(key)
        if isinstance(value, list):
            explicit += len(value)
    # Count non-image Markdown source links in the final suffix.
    md_links = re.findall(r"(?<!!)\[[^\]]+\]\(https?://[^)]+\)", content)
    return max(explicit, len(md_links))


def check_rag_query(gateway_url: str, model: str, golden: dict[str, Any], timeout: float) -> CheckResult:
    start = time.perf_counter()
    query = str(golden.get("query") or "").strip()
    expected_min_sources = int(golden.get("expected_min_sources") or 1)
    max_latency = int(golden.get("expected_max_latency_ms") or 30000)
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": query}],
        "stream": False,
        "temperature": 0,
        "max_tokens": 180,
    }
    try:
        status_code, data, latency = http_json(f"{gateway_url}/v1/chat/completions", payload, timeout=min(timeout, max_latency / 1000 + 5))
    except urllib.error.HTTPError as exc:
        return result("FAIL", True, start, {"status_code": exc.code}, f"rag query HTTP {exc.code}")
    except Exception as exc:
        return result("FAIL", True, start, {}, f"rag query failed: {type(exc).__name__}")
    try:
        content = data["choices"][0]["message"]["content"]
    except Exception:
        content = ""
    sources_count = count_sources(data, content)
    answer_chars = len(content)
    details = {
        "status_code": status_code,
        "latency_ms": latency,
        "answer_chars": answer_chars,
        "answer_preview": content[:200],
        "sources_count": sources_count,
        "sources_detected": sources_count >= expected_min_sources,
        "expected_min_sources": expected_min_sources,
        "expected_max_latency_ms": max_latency,
    }
    if status_code != 200:
        return result("FAIL", True, start, details, f"rag query returned HTTP {status_code}")
    if answer_chars <= 50:
        return result("FAIL", True, start, details, "rag answer was empty or too short")
    if sources_count < expected_min_sources:
        return result("FAIL", True, start, details, f"rag answer had {sources_count} sources, expected at least {expected_min_sources}")
    if latency > max_latency:
        return result("FAIL", True, start, details, f"rag query latency {latency} ms exceeded {max_latency} ms")
    return result("PASS", True, start, details)


def parse_ollama_ps_json(stdout: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    raw = stdout.strip()
    if not raw:
        return rows
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return rows
    items: list[Any]
    if isinstance(parsed, list):
        items = parsed
    elif isinstance(parsed, dict):
        value = parsed.get("models") or parsed.get("items")
        items = value if isinstance(value, list) else [parsed]
    else:
        return rows
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("name") or item.get("model")
        processor = item.get("processor") or item.get("processors")
        if not isinstance(name, str):
            continue
        rows.append(
            {
                "name": name,
                "id": str(item.get("id") or ""),
                "size": str(item.get("size") or ""),
                "processor": str(processor or "unknown"),
                "raw": json.dumps(item, ensure_ascii=False, sort_keys=True),
            }
        )
    return rows


def parse_ollama_ps_table(stdout: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    lines = [line.rstrip() for line in stdout.splitlines() if line.strip()]
    if len(lines) <= 1:
        return rows
    for line in lines[1:]:
        parts = re.split(r"\s{2,}", line.strip())
        if len(parts) < 4:
            rows.append({"raw": line})
            continue
        row = {
            "name": parts[0],
            "id": parts[1],
            "size": parts[2],
            "processor": parts[3],
            "raw": line,
        }
        if len(parts) > 4:
            row["context"] = parts[4]
        if len(parts) > 5:
            row["until"] = parts[5]
        rows.append(row)
    return rows


def parse_gpu_percent(processor: str) -> int | None:
    text = processor.strip()
    gpu_match = re.search(r"(\d{1,3})\s*%\s*GPU", text, flags=re.IGNORECASE)
    if gpu_match:
        return max(0, min(100, int(gpu_match.group(1))))
    cpu_match = re.search(r"(\d{1,3})\s*%\s*CPU", text, flags=re.IGNORECASE)
    if cpu_match:
        return max(0, min(100, 100 - int(cpu_match.group(1))))
    return None


def check_ollama_text_model_gpu_placement(model: str, timeout: float) -> CheckResult:
    start = time.perf_counter()
    require_gpu = env_bool("DEMO_HEALTH_REQUIRE_TEXT_GPU", True)
    recovery_hint = (
        "Recovery: docker compose restart ollama; wait 20s; send one warm-up "
        "request; docker compose exec ollama ollama ps"
    )
    json_cp = run_cmd(
        ["docker", "compose", "exec", "-T", "ollama", "ollama", "ps", "--format", "json"],
        timeout=min(10, timeout),
    )
    rows: list[dict[str, str]] = []
    inspection_method = "json"
    table_cp: subprocess.CompletedProcess[str] | None = None
    json_attempt_error = ""
    if json_cp.returncode == 0:
        rows = parse_ollama_ps_json(json_cp.stdout)
        if not rows:
            json_attempt_error = "JSON output was empty or unrecognized"
    else:
        json_attempt_error = json_cp.stderr.strip() or json_cp.stdout.strip() or f"exit {json_cp.returncode}"
    if not rows:
        inspection_method = "table"
        table_cp = run_cmd(
            ["docker", "compose", "exec", "-T", "ollama", "ollama", "ps"],
            timeout=min(10, timeout),
        )
        if table_cp.returncode == 0:
            rows = parse_ollama_ps_table(table_cp.stdout)

    cp = table_cp or json_cp
    details: dict[str, Any] = {
        "name": "ollama_text_model_gpu_placement",
        "model": model,
        "processor": "unknown",
        "gpu_percent": None,
        "require_gpu": require_gpu,
        "raw_line": None,
        "message": "",
        "inspection_method": inspection_method,
        "json_attempt_error": json_attempt_error,
        "command": "docker compose exec -T ollama ollama ps",
        "stdout": cp.stdout.strip(),
        "stderr": cp.stderr.strip(),
    }
    if cp.returncode != 0:
        details["returncode"] = cp.returncode
        details["message"] = f"cannot inspect ollama ps: {cp.stderr.strip() or cp.stdout.strip() or f'exit {cp.returncode}'}"
        return result("FAIL", True, start, details, details["message"])

    details["loaded_models"] = rows
    target_names = normalize_model_name(model)
    match = next(
        (
            row
            for row in rows
            if row.get("name") in target_names
            or normalize_model_name(row.get("name", "")) & target_names
        ),
        None,
    )
    if not match:
        loaded_names = [row.get("name") for row in rows if row.get("name")]
        details["loaded_model_names"] = loaded_names
        details["message"] = (
            f"text model {model} is not currently loaded after rag_query; "
            "rag_query should have loaded it, so re-run after a warm-up request if Ollama evicted it between checks"
        )
        status = "WARN" if not require_gpu else "FAIL"
        required = require_gpu
        return result(status, required, start, details, details["message"])

    processor = match.get("processor", "unknown") or "unknown"
    gpu_percent = parse_gpu_percent(processor)
    details["matched_model"] = match
    details["processor"] = processor
    details["gpu_percent"] = gpu_percent
    details["raw_line"] = match.get("raw")

    if gpu_percent is not None and gpu_percent >= 90:
        details["message"] = f"text model {model} processor is {processor}"
        return result("PASS", True, start, details)

    if gpu_percent is not None and gpu_percent >= 50:
        details["message"] = (
            f"text model {model} processor is {processor}; substantial CPU offload may slow demos"
        )
        return result("WARN", False, start, details, details["message"])

    if gpu_percent is None:
        details["message"] = f"text model {model} processor is {processor}; unable to parse GPU percentage"
    else:
        details["message"] = f"text model {model} processor is {processor}; {recovery_hint}"
    status = "WARN" if not require_gpu else "FAIL"
    required = require_gpu
    return result(status, required, start, details, details["message"])


def check_recent_ingest(timeout: float, env: dict[str, str]) -> CheckResult:
    start = time.perf_counter()
    db = env.get("RAG_DB") or "rag"
    user = env.get("POSTGRES_USER") or "rag_user"
    column_sql = (
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name='rag_chunks' AND column_name='created_at';"
    )
    column_cp = run_cmd(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "postgres",
            "psql",
            "-h",
            "127.0.0.1",
            "-U",
            user,
            "-d",
            db,
            "-tA",
            "-c",
            column_sql,
        ],
        timeout=min(10, timeout),
    )
    if column_cp.returncode != 0:
        return result("SKIP", False, start, {}, "could not inspect rag_chunks.created_at")
    if column_cp.stdout.strip() != "1":
        return result(
            "SKIP",
            False,
            start,
            {"created_at_column_present": False},
            "rag_chunks.created_at column is absent in current schema",
        )
    sql = "SELECT COALESCE(MAX(created_at)::text, '') FROM rag_chunks;"
    cp = run_cmd(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "postgres",
            "psql",
            "-h",
            "127.0.0.1",
            "-U",
            user,
            "-d",
            db,
            "-tA",
            "-c",
            sql,
        ],
        timeout=min(10, timeout),
    )
    if cp.returncode != 0:
        return result("SKIP", False, start, {}, "could not read newest rag_chunks timestamp")
    raw = cp.stdout.strip()
    details: dict[str, Any] = {"newest_chunk_created_at": raw or None}
    if not raw:
        return result("WARN", False, start, details, "rag_chunks has no created_at values")
    try:
        dt = datetime.fromisoformat(raw.replace(" ", "T"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age_days = (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds() / 86400
        details["newest_chunk_age_days"] = round(age_days, 2)
        if age_days > 7:
            return result("WARN", False, start, details, f"newest chunk is {age_days:.1f} days old")
    except Exception:
        return result("WARN", False, start, details, "could not parse newest chunk timestamp")
    return result("PASS", False, start, details)


def check_alert_stub_configured() -> str | None:
    if os.environ.get("DEMO_HEALTH_ALERT_WEBHOOK"):
        return "DEMO_HEALTH_ALERT_WEBHOOK is set, but real alerting is intentionally deferred; notify.sh is a local log-only stub."
    return None


def render_markdown(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"# Demo E2E Health: {payload['status']}")
    lines.append("")
    lines.append(f"- **Timestamp:** {payload['timestamp']}")
    lines.append(f"- **Last successful pass:** {payload.get('last_pass_ts') or 'never'}")
    lines.append(f"- **Selected query:** `{payload.get('selected_query_id')}`")
    lines.append(f"- **Selected model:** `{payload.get('selected_model')}`")
    if payload.get("failed_check"):
        lines.append(f"- **Failed check:** `{payload['failed_check']}` — {payload.get('failure_reason')}")
    lines.append("")
    lines.append("## Checks")
    lines.append("")
    lines.append("| check | required | status | latency_ms | reason |")
    lines.append("|---|:---:|---:|---:|---|")
    for name, check in payload["checks"].items():
        lines.append(
            f"| `{name}` | {'Y' if check['required'] else 'N'} | **{check['status']}** | "
            f"{check['latency_ms']} | {check.get('reason') or ''} |"
        )
    lines.append("")
    rq = payload.get("rag_query") or {}
    lines.append("## RAG Query Summary")
    lines.append("")
    lines.append(f"- Latency: **{rq.get('latency_ms')} ms**")
    lines.append(f"- Answer chars: **{rq.get('answer_chars')}**")
    lines.append(f"- Sources detected: **{rq.get('sources_detected')}** ({rq.get('sources_count')})")
    preview = rq.get("answer_preview")
    if preview:
        lines.append(f"- Preview: `{preview}`")
    lines.append("")
    if payload.get("warnings"):
        lines.append("## Warnings")
        lines.append("")
        for warning in payload["warnings"]:
            lines.append(f"- {warning}")
        lines.append("")
    if payload["status"] == "FAIL":
        lines.append("## Suggested Next Action")
        lines.append("")
        lines.append(f"Start with `{payload.get('failed_check')}`. Read `details` for that check in `latest.json`; do not restart containers until the failure is understood.")
        lines.append("")
    return "\n".join(lines) + "\n"


def serialize_checks(checks: dict[str, CheckResult]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, check in checks.items():
        out[name] = {
            "status": check.status,
            "required": check.required,
            "latency_ms": check.latency_ms,
            "duration_ms": check.latency_ms,
            "details": check.details,
        }
        if name == "ollama_text_model_gpu_placement":
            for key in (
                "name",
                "model",
                "processor",
                "gpu_percent",
                "require_gpu",
                "raw_line",
                "message",
            ):
                out[name][key] = check.details.get(key)
        if check.reason:
            out[name]["reason"] = check.reason
    return out


def write_reports(payload: dict[str, Any], ts: datetime) -> None:
    HEALTH_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    json_text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    md_text = render_markdown(payload)
    atomic_write(LATEST_JSON, json_text)
    atomic_write(LATEST_MD, md_text)
    stamp = history_stamp(ts)
    atomic_write(HISTORY_DIR / f"{stamp}_health.json", json_text)
    atomic_write(HISTORY_DIR / f"{stamp}_health.md", md_text)


def main() -> int:
    started = time.perf_counter()
    ts = now_local()
    env = load_env()
    model = active_model(env)
    timeout = float(os.environ.get("DEMO_HEALTH_TIMEOUT_SECS", "60"))
    min_disk = float(os.environ.get("DEMO_HEALTH_MIN_DISK_GB", "5"))
    project = compose_project_name(env)
    golden = load_golden_query(model)
    gateway_url = gateway_url_from_compose(timeout=min(5, timeout))

    checks: dict[str, CheckResult] = {}
    warnings: list[str] = []
    failed_check: str | None = None
    failure_reason: str | None = None

    def add(name: str, check: CheckResult) -> bool:
        nonlocal failed_check, failure_reason
        checks[name] = check
        if check.status == "WARN" and check.reason:
            warnings.append(check.reason)
        if check.required and check.status != "PASS":
            failed_check = name
            failure_reason = check.reason or f"{name} failed"
            return False
        return True

    alert_warning = check_alert_stub_configured()
    if alert_warning:
        warnings.append(alert_warning)

    if add("disk_space", check_disk_space(min_disk)):
        if add("compose_services", check_compose_services(timeout, project)):
            if add("health_endpoints", check_health_endpoints(gateway_url, timeout, env)):
                if add("ollama_models", check_ollama_models(model, timeout)):
                    if add("embedding_spot_check", check_embedding_spot(timeout)):
                        if add("trace_dir_writable", check_trace_dir()):
                            if add("rag_query", check_rag_query(gateway_url, model, golden, timeout)):
                                add("ollama_text_model_gpu_placement", check_ollama_text_model_gpu_placement(model, timeout))
                                add("recent_ingest", check_recent_ingest(timeout, env))

    status = "FAIL" if failed_check else "PASS"
    timestamp = ts.isoformat(timespec="seconds")
    previous_last_pass = read_previous_last_pass()
    last_pass_ts = timestamp if status == "PASS" else previous_last_pass
    rag_details = checks.get("rag_query").details if "rag_query" in checks else {}
    payload = {
        "timestamp": timestamp,
        "status": status,
        "duration_ms": elapsed_ms(started),
        "last_pass_ts": last_pass_ts,
        "selected_query_id": golden.get("prompt_id") or golden.get("query_id"),
        "selected_model": model,
        "selected_query": golden.get("query"),
        "checks": serialize_checks(checks),
        "rag_query": {
            "latency_ms": rag_details.get("latency_ms"),
            "answer_chars": rag_details.get("answer_chars"),
            "sources_detected": rag_details.get("sources_detected"),
            "sources_count": rag_details.get("sources_count"),
            "answer_preview": rag_details.get("answer_preview"),
        },
        "failed_check": failed_check,
        "failure_reason": failure_reason,
        "warnings": warnings,
    }
    write_reports(payload, ts)

    print(f"DEMO_E2E_STATUS={status}")
    print(f"duration_ms={payload['duration_ms']}")
    print(f"latest_json={LATEST_JSON.relative_to(ROOT)}")
    print(f"latest_md={LATEST_MD.relative_to(ROOT)}")
    print(f"selected_query_id={payload['selected_query_id']}")
    print(f"selected_model={model}")
    if failed_check:
        print(f"failed_check={failed_check}")
        print(f"failure_reason={failure_reason}")
    for name, check in checks.items():
        suffix = f" reason={check.reason}" if check.reason else ""
        print(f"{name}={check.status} latency_ms={check.latency_ms}{suffix}")
    if warnings:
        for warning in warnings:
            print(f"warning={warning}")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
