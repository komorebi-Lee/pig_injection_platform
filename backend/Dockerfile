FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Shanghai

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock* ./
RUN pip install --no-cache-dir uv \
 && uv pip install --system --no-cache \
      "fastapi>=0.115" "uvicorn[standard]>=0.30" "sqlalchemy>=2.0.30" \
      "psycopg[binary]>=3.1" "pydantic>=2.7" "pydantic-settings>=2.3" \
      "python-multipart>=0.0.9" "httpx>=0.27"

COPY . .

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8080/api/v1/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
