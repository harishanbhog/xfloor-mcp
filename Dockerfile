# syntax=docker/dockerfile:1

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY xfloor_mcp ./xfloor_mcp
COPY openai_widget/dist ./openai_widget/dist

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

EXPOSE 8000

CMD ["uvicorn", "xfloor_mcp.server_http:app", "--host", "0.0.0.0", "--port", "8000"]
