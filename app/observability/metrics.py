"""
Prometheus 指标定义与中间件。
"""
import time
import logging
from fastapi import Request, Response
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

REQUESTS_TOTAL = Counter(
    "woolgate_requests_total",
    "Total requests",
    ["method", "path", "status"]
)
REQUEST_DURATION = Histogram(
    "woolgate_request_duration_seconds",
    "Request duration in seconds",
    ["method", "path"]
)
INPROGRESS = Gauge(
    "woolgate_inprogress_requests",
    "In-progress requests"
)
UPSTREAM_ERRORS = Counter(
    "woolgate_upstream_errors_total",
    "Upstream errors",
    ["vendor", "model", "error_type"]
)


class PrometheusMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path.startswith("/metrics") or path.startswith("/_nicegui"):
            return await call_next(request)
        INPROGRESS.inc()
        start = time.time()
        status = "500"
        try:
            response = await call_next(request)
            status = str(response.status_code)
            return response
        finally:
            duration = time.time() - start
            REQUESTS_TOTAL.labels(method=request.method, path=path, status=status).inc()
            REQUEST_DURATION.labels(method=request.method, path=path).observe(duration)
            INPROGRESS.dec()


def setup_metrics(app):
    app.add_middleware(PrometheusMiddleware)

    @app.get("/metrics")
    async def metrics():
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    logger.info("Prometheus metrics 已挂载：/metrics")
