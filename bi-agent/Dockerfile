FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    WHATSAPP_INBOX_PATH=/data/whatsapp-inbox.sqlite3

WORKDIR /app
COPY pyproject.toml .
COPY whatsapp_bi ./whatsapp_bi
RUN python -m pip install --no-cache-dir . \
    && install -d -m 700 -o 10001 -g 10001 /data

USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "from urllib.request import urlopen; urlopen('http://127.0.0.1:8000/health/', timeout=2).close()"
CMD ["uvicorn", "whatsapp_bi.web:from_env", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]
