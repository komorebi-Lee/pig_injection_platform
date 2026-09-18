"""WebSocket：实时推送机械臂状态、注射阶段、告警。"""

from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..services import registry, ws

router = APIRouter(tags=["实时推送"])


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """连接后立即推一次当前状态，之后由遥测轮询和指令通道持续推送。

    消息格式统一为 {"type": "...", "data": {...}}：
      - arm_status       机械臂状态（遥测间隔一次）
      - control_command  指令执行结果
      - injection_phase  注射阶段变化
      - injection_task   注射任务终态
      - obstacle         避障事件
    """
    await ws.hub.connect(websocket)
    try:
        adapter = registry.get_adapter()
        try:
            status = adapter.get_status()
            status.pop("raw", None)
            await websocket.send_json({"type": "arm_status", "data": status})
        except Exception:
            pass

        while True:
            message = await websocket.receive_text()
            if message == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        await ws.hub.disconnect(websocket)
