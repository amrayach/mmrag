import asyncio
import logging
from typing import Optional

import docker
from docker.models.containers import Container

from . import config

logger = logging.getLogger("controlcenter.docker")

client: Optional[docker.DockerClient] = None


def init_client():
    global client
    client = docker.from_env()
    logger.info("Docker client initialized")


def close_client():
    global client
    if client:
        client.close()
        client = None
        logger.info("Docker client closed")


def _validate_name(name: str) -> str:
    """Validate container name starts with our prefix. Returns full name."""
    full_name = name if name.startswith(config.CONTAINER_PREFIX) else f"{config.CONTAINER_PREFIX}{name}"
    if not full_name.startswith(config.CONTAINER_PREFIX):
        raise ValueError(f"Container name must start with {config.CONTAINER_PREFIX}")
    return full_name


def _get_container(name: str) -> Container:
    full_name = _validate_name(name)
    return client.containers.get(full_name)


def _container_to_dict(c: Container) -> dict:
    """Convert container to serializable dict."""
    health = "none"
    if c.attrs.get("State", {}).get("Health"):
        health = c.attrs["State"]["Health"].get("Status", "unknown")

    ports = []
    port_bindings = c.attrs.get("HostConfig", {}).get("PortBindings") or {}
    for container_port, bindings in port_bindings.items():
        if bindings:
            for b in bindings:
                ports.append({
                    "container_port": container_port,
                    "host_ip": b.get("HostIp", ""),
                    "host_port": b.get("HostPort", ""),
                })

    short_name = c.name
    if short_name.startswith(config.CONTAINER_PREFIX):
        short_name = short_name[len(config.CONTAINER_PREFIX):]

    return {
        "name": c.name,
        "short_name": short_name,
        "state": c.status,
        "health": health,
        "status": c.attrs.get("State", {}).get("Status", c.status),
        "image": c.image.tags[0] if c.image.tags else c.image.short_id,
        "ports": ports,
        "created": c.attrs.get("Created", ""),
    }


# ---------------------------------------------------------------------------
# Async wrappers (offload blocking Docker SDK calls to threadpool)
# ---------------------------------------------------------------------------

async def list_containers() -> list[dict]:
    def _list():
        containers = client.containers.list(all=True)
        return [
            _container_to_dict(c)
            for c in containers
            if c.name.startswith(config.CONTAINER_PREFIX)
        ]
    return await asyncio.to_thread(_list)


async def get_container_info(name: str) -> dict:
    def _get():
        c = _get_container(name)
        c.reload()
        return _container_to_dict(c)
    return await asyncio.to_thread(_get)


async def get_container_stats(name: str) -> dict:
    def _stats():
        c = _get_container(name)
        return c.stats(stream=False)
    return await asyncio.to_thread(_stats)


async def get_container_env(name: str) -> list[dict]:
    def _env():
        c = _get_container(name)
        c.reload()
        env_list = c.attrs.get("Config", {}).get("Env", [])
        result = []
        for entry in env_list:
            key, _, value = entry.partition("=")
            # Mask secrets
            if any(pat in key.upper() for pat in config.SECRET_PATTERNS):
                value = "***"
            result.append({"key": key, "value": value})
        return result
    return await asyncio.to_thread(_env)


async def start_container(name: str) -> str:
    full_name = _validate_name(name)

    def _start():
        c = client.containers.get(full_name)
        c.start()
        return f"Started {full_name}"
    return await asyncio.to_thread(_start)


async def stop_container(name: str) -> str:
    full_name = _validate_name(name)

    def _stop():
        c = client.containers.get(full_name)
        c.stop(timeout=30)
        return f"Stopped {full_name}"
    return await asyncio.to_thread(_stop)


async def restart_container(name: str) -> str:
    full_name = _validate_name(name)

    def _restart():
        c = client.containers.get(full_name)
        c.restart(timeout=30)
        return f"Restarted {full_name}"
    return await asyncio.to_thread(_restart)


async def get_container_logs(name: str, tail: int = 100) -> str:
    """Get static logs (for stopped containers or one-shot)."""
    def _logs():
        c = _get_container(name)
        return c.logs(tail=tail, timestamps=True).decode("utf-8", errors="replace")
    return await asyncio.to_thread(_logs)


async def stream_container_logs(name: str, tail: int = 100) -> asyncio.Queue:
    """Start streaming logs in a thread, return an async queue of log lines."""
    q: asyncio.Queue = asyncio.Queue(maxsize=500)
    loop = asyncio.get_event_loop()

    def _stream():
        try:
            c = _get_container(name)
            for line in c.logs(stream=True, follow=True, tail=tail, timestamps=True):
                text = line.decode("utf-8", errors="replace")
                asyncio.run_coroutine_threadsafe(q.put(text), loop)
        except Exception as e:
            asyncio.run_coroutine_threadsafe(
                q.put(f"[Log stream error: {e}]\n"), loop
            )
        finally:
            asyncio.run_coroutine_threadsafe(q.put(None), loop)  # sentinel

    asyncio.get_event_loop().run_in_executor(None, _stream)
    return q


async def docker_ping() -> bool:
    def _ping():
        client.ping()
        return True
    try:
        return await asyncio.to_thread(_ping)
    except Exception:
        return False
