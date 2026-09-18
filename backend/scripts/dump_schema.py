"""从 ORM 模型导出 PostgreSQL DDL 到 sql/schema.sql（供 DBA 评审 / 手工建库用）。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from app.models import Base

OUT = Path(__file__).resolve().parent.parent / "sql" / "schema.sql"


def main() -> None:
    dialect = postgresql.dialect()
    chunks: list[str] = [
        "-- 由 scripts/dump_schema.py 自动生成，请勿手工编辑。",
        "-- 权威定义在 app/models.py。",
        "",
    ]
    for table in Base.metadata.sorted_tables:
        chunks.append(str(CreateTable(table).compile(dialect=dialect)).strip() + ";")
        for index in sorted(table.indexes, key=lambda i: i.name or ""):
            chunks.append(str(CreateIndex(index).compile(dialect=dialect)).strip() + ";")
        chunks.append("")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(chunks), encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
