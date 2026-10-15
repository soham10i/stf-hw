# The live twin as ONE container: the FastAPI physics kernel (REST + WebSocket) serving the
# built web app on the same origin. Used by Render (render.yaml, service "stf-live") and
# runnable anywhere:
#   docker build -t stf-live . && docker run -p 10000:10000 stf-live   ->  http://localhost:10000/
# No database, Redis or MQTT: the API's runtime keeps its state in memory (services/api/runtime.py).

# ---- 1. the web app, built for the live API (base /stf/) ----
FROM node:20-slim AS web
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# ---- 2. the API ----
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/packages \
    STF_WEB_DIST=/app/web/dist \
    PORT=10000
WORKDIR /app
RUN pip install --no-cache-dir "pydantic>=2.9" "pyyaml>=6.0" "numpy>=1.26" \
    "fastapi>=0.115" "uvicorn[standard]>=0.30" "websockets>=13"
COPY packages/ packages/
COPY services/ services/
COPY --from=web /app/web/dist web/dist
RUN useradd --create-home --uid 10001 stf && chown -R stf /app
USER stf
EXPOSE 10000
# Render sets $PORT; the proxy in front of it sets X-Forwarded-For (the rate limiter's client).
CMD ["sh", "-c", "exec uvicorn services.api.app:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
