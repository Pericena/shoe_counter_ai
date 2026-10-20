FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_ENV=production \
    STORAGE_DIR=/data/storage \
    AI_MODELS_DIR=/data/modelos \
    WEB_DIR=/srv/web

WORKDIR /srv/backend

# libgomp1: requerida por onnxruntime en imágenes slim.
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt backend/requirements-nodeps.txt ./
RUN pip install -r requirements.txt && pip install --no-deps -r requirements-nodeps.txt

COPY backend/ /srv/backend/
COPY web/ /srv/web/

RUN useradd --create-home --uid 10001 app \
    && mkdir -p /data/storage /data/modelos \
    && chown -R app:app /data \
    && chmod +x /srv/backend/docker-entrypoint.sh

USER app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"

ENTRYPOINT ["/srv/backend/docker-entrypoint.sh"]
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "--timeout", "120", "--access-logfile", "-", "run:app"]
