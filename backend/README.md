# backend · 机械臂猪只背部注射系统后端

FastAPI + SQLAlchemy 2.0 + PostgreSQL 17。
本服务是**机械臂指令的唯一出口**，同时负责把机械臂回传的一切数据落库。

## 快速跑起来

```powershell
# 1. 起数据库（便携版，见 docs/03_快速开始.md）
powershell -ExecutionPolicy Bypass -File scripts\pg_start.ps1

# 2. 建表 + 种子
uv sync
uv run python scripts/init_db.py

# 3. 起服务
uv run uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload

# 4. 自检（42 项断言）
uv run python scripts/smoke_test.py
```

接口文档：http://127.0.0.1:8080/docs

## 分层

```
api/           HTTP 路由，只做参数校验与响应组装
  └ services/  业务逻辑
       ├ commands.py    指令通道：幂等 + 审计 + 广播（所有控制指令必经）
       ├ arm_gateway.py 机械臂适配器（Mock / HTTP）
       ├ telemetry.py   后台轮询：状态 -> 数据库 -> 告警 -> WebSocket
       ├ injection.py   注射状态机（created..completed）
       ├ alarms.py      告警产生与 60 秒去重
       ├ media.py       媒体落盘与登记
       └ ws.py          WebSocket 广播中心
  └ models.py   17 张表的权威定义（schema.sql 由此导出）
  └ schemas.py  前端契约（请求/响应模型）
```

## 四条设计约束（改代码前请先读）

1. **任何发往机械臂的指令都必须走 `services.commands.dispatch()`**。
   它保证幂等（`request_id`）、审计（`control_commands`）、错误归一、WebSocket 广播。
   绕过它直接调 adapter 会让审计链断掉。
2. **`app/models.py` 是表结构的唯一权威来源**。改完模型跑
   `uv run python scripts/dump_schema.py` 更新 `sql/schema.sql`，不要手改 SQL。
3. **机械臂的字段差异只能出现在 `arm_gateway.py`**。业务代码、API、前端都不能感知
   "这家机械臂叫 joints 那家叫 joint_angles"。
4. **急停必须幂等、无前置条件、可重复调用**。不要在它前面加任何校验。

## 配置

全部走环境变量，见 `.env.example`。关键项：

| 变量 | 说明 |
|---|---|
| `DATABASE_URL` | 数据库连接串 |
| `ARM_DRIVER` | `mock`（无硬件联调）/ `http`（真机） |
| `ARM_BASE_URL` | 外包方控制服务地址 |
| `ARM_PATH_*` | 对方接口路径映射 |
| `TELEMETRY_INTERVAL_S` | 遥测轮询间隔，默认 1 秒 |
| `TELEMETRY_RETENTION_DAYS` | 高频遥测保留天数，默认 30 |
| `FEVER_TEMP_C` | 体温告警阈值，默认 40.5 |
| `DEFAULT_DEVICE_CODE` | 默认机械臂编号，默认 ARM-01 |

## 常用命令

```powershell
uv run python scripts/init_db.py --drop     # 重建数据库（危险）
uv run python scripts/dump_schema.py        # 导出 DDL
uv run python scripts/smoke_test.py         # 端到端自检
uv run ruff check app scripts               # 静态检查
uv run pytest -q                            # 单元测试
```

## 已知边界

- v1 无鉴权，只允许部署在可信局域网。
- 一次只允许一个注射任务在执行（由机械臂侧状态机保证）。
- `injection_tasks` / `control_commands` / `alarms` 是审计数据，只追加不修改。
