"""后端服务入口。

启动：
    uv run uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload

设计要点：
- 前端只与本服务通信，机械臂指令的唯一出口在这里；
- 所有控制类接口都经 services.commands.dispatch()，天然带幂等与审计；
- /api/v1/ws 提供实时推送，前端不必高频轮询。
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import HTTPException as FastAPIHTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import settings
from .db import engine
from .services import registry, telemetry, ws
from .services.arm_gateway import ArmGatewayError
from .services.commands import CommandRejected

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=" * 72)
    logger.info("%s v%s 启动", settings.app_name, settings.app_version)
    logger.info("数据库：%s", settings.database_url.rsplit("@", 1)[-1])
    logger.info("机械臂驱动：%s", settings.arm_driver)
    logger.info("接口文档：http://127.0.0.1:8080/docs")
    logger.info("=" * 72)

    ws.bind_loop(asyncio.get_running_loop())
    settings.media_root.mkdir(parents=True, exist_ok=True)

    if settings.telemetry_enabled:
        telemetry.poller.start()

    try:
        yield
    finally:
        telemetry.poller.stop()
        registry.get_adapter().close()
        engine.dispose()
        logger.info("服务已停止")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "机械臂猪只背部注射系统后端。\n\n"
        "**前端同学请看** `docs/02_后端接口契约_v1.md`，或直接访问 `/docs` 在线调试。\n\n"
        "约定：所有写操作请携带 `request_id` 作为幂等键；错误统一返回 "
        "`{ok:false, error, message}`。"
    ),
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def no_cache_json(request: Request, call_next):
    response = await call_next(request)
    if response.headers.get("content-type", "").startswith("application/json"):
        response.headers["Cache-Control"] = "no-store"
    return response


# ---------------------------------------------------------------------------
# 统一错误响应
# ---------------------------------------------------------------------------


@app.exception_handler(CommandRejected)
async def command_rejected_handler(request: Request, exc: CommandRejected) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status,
        content={
            "ok": False,
            "error": exc.code,
            "message": str(exc),
            "request_id": exc.request_id,
        },
    )


@app.exception_handler(ArmGatewayError)
async def arm_error_handler(request: Request, exc: ArmGatewayError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status,
        content={"ok": False, "error": exc.code, "message": str(exc)},
    )


# 分类码：让前端只靠 error 字段就能决定怎么处理，不必解析中文文案
_HTTP_ERROR_SLUGS = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    422: "validation_error",
}


@app.exception_handler(FastAPIHTTPException)
async def http_exception_handler(request: Request, exc: FastAPIHTTPException) -> JSONResponse:
    """把 FastAPI 默认的 {detail} 归一成 {ok, error, message}，并保留 detail 兼容旧调用。"""
    detail = exc.detail
    message = detail if isinstance(detail, str) else json.dumps(jsonable_encoder(detail), ensure_ascii=False)
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "ok": False,
            "error": _HTTP_ERROR_SLUGS.get(exc.status_code, "http_error"),
            "message": message,
            "detail": detail,
        },
        headers=getattr(exc, "headers", None),
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = jsonable_encoder(exc.errors())
    first = errors[0] if errors else {}
    location = ".".join(str(part) for part in first.get("loc", []))
    message = f"参数校验失败：{location} {first.get('msg', '')}".strip()
    return JSONResponse(
        status_code=422,
        content={"ok": False, "error": "validation_error", "message": message, "detail": errors},
    )


# ---------------------------------------------------------------------------
# 路由挂载
# ---------------------------------------------------------------------------

from .api import (  # noqa: E402  (放在异常处理器之后挂载，导入顺序更清晰)
    alarms_api,
    arm,
    catalog,
    devices,
    injection,
    media_api,
    perception,
    reports,
    system,
    ws_api,
)

for module in (system, devices, arm, injection, perception, catalog, alarms_api, media_api, reports, ws_api):
    app.include_router(module.router, prefix=settings.api_prefix)
