FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY fanout_live ./fanout_live

RUN python -m compileall fanout_live

EXPOSE 1935
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import json, urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=3).read()"

CMD ["python", "-m", "fanout_live", "--web", "--config", "/config/config.toml", "--web-host", "0.0.0.0", "--web-port", "8080"]
