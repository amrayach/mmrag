from pydantic import BaseModel
from typing import Optional


class HealthResponse(BaseModel):
    ok: bool


class ReadyResponse(BaseModel):
    ok: bool
    checks: dict


class ContainerInfo(BaseModel):
    name: str
    short_name: str
    state: str  # running, stopped, paused, etc.
    health: str  # healthy, unhealthy, none, unknown
    status: str  # Docker status string (e.g. "Up 2 hours (healthy)")
    image: str
    ports: list[dict]
    created: str


class DashboardMetrics(BaseModel):
    containers_up: int
    containers_total: int
    total_docs: int
    total_chunks: int
    total_images: int


class ServiceAction(BaseModel):
    service: str
    action: str
    result: str
