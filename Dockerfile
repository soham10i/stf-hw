# The live twin as ONE container: the FastAPI physics kernel (REST + WebSocket) serving the
# built web app on the same origin. Used by Cloud Run (docs/GCP_DEPLOY.md) and
# runnable anywhere:
#   docker build -t stf-live . && docker run -p 10000:10000 stf-live   ->  http://localhost:10000/
# No database, Redis or MQTT: the API's runtime keeps its state in memory (services/api/runtime.py).

# Base images are pinned by digest (a tag can be re-pointed): refresh them on a schedule with
#   docker buildx imagetools inspect python:3.12-slim   (and node:20-slim)
# so Debian's security fixes arrive (docs/SECURITY_FINDINGS.md, F7).

# ---- 1. the web app, built for the live API (base /stf/) ----
FROM node:20-slim@sha256:2cf067cfed83d5ea958367df9f966191a942351a2df77d6f0193e162b5febfc0 AS web
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# ---- 2. the API ----
FROM python:3.12-slim@sha256:cb33f7f771ecec2ef1225cf39b159591a040391bd73e4c01f00fdfc4c47611d2
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/packages \
    STF_WEB_DIST=/app/web/dist \
    PORT=10000
WORKDIR /app
# exact versions with hashes (requirements-api.in -> requirements-api.txt): every build installs
# the same reviewed packages, and a tampered download fails the hash check
COPY requirements-api.txt .
RUN pip install --no-cache-dir --require-hashes -r requirements-api.txt
COPY packages/ packages/
COPY services/ services/
# the copilot's page guides (tools.page_guide); the twin's data it reads is in web/dist
COPY docs/assistant/ docs/assistant/
COPY --from=web /app/web/dist web/dist
RUN useradd --create-home --uid 10001 stf && chown -R stf /app
USER stf
EXPOSE 10000
# The platform sets $PORT. uvicorn rewrites the client address from X-Forwarded-For only for a
# loopback peer (its default): with '*' any visitor could choose their own address. The API reads
# the proxy's entry itself (security.client_ip, STF_PROXY_HOPS; automatic on Cloud Run).
# --ws-max-size: a WebSocket frame larger than the biggest live-link message (livehub.MAX_MSG,
# 320 kB) is refused before it is buffered (uvicorn's default would hold up to 16 MiB).
CMD ["sh", "-c", "exec uvicorn services.api.app:app --host 0.0.0.0 --port ${PORT} --proxy-headers --ws-max-size 400000"]
