"""路由公共依赖与小工具。"""

from __future__ import annotations

from fastapi import Request

from ..services.commands import CommandRejected


def client_ip(request: Request) -> str | None:
    if request.client is None:
        return None
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    return request.client.host


__all__ = ["CommandRejected", "client_ip"]
