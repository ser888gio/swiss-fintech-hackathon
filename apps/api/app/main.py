import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import db, store
from .config import get_settings
from .routes import credentials, health, payments, treasury, wallet
from .routes.agents import router as agents_router, load_agents_from_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    if await db.init_db(settings.database_url):
        await store.load_from_db()
        from .tools import insurance as insurance_tool
        await insurance_tool.load_from_db()
        await load_agents_from_db()
    yield


app = FastAPI(title="Treasury Agent API", version="0.1.0", lifespan=lifespan)
settings = get_settings()
cors_origins = [
    origin.strip()
    for origin in settings.cors_origins.split(",")
    if origin.strip()
]
if settings.railway_service_web_url:
    web_origin = settings.railway_service_web_url.strip()
    if not web_origin.startswith(("http://", "https://")):
        web_origin = f"https://{web_origin}"
    if web_origin not in cors_origins:
        cors_origins.append(web_origin)

# Vite may be opened through either loopback hostname and can move to the next
# available port when 5173 is occupied. Keep this independent of CORS_ORIGINS
# so an older/local .env cannot accidentally break browser development.
local_dev_origin_regex = r"http://(?:localhost|127\.0\.0\.1):\d+"
cors_origin_regex = (
    rf"(?:{settings.cors_origin_regex})|(?:{local_dev_origin_regex})"
    if settings.cors_origin_regex
    else local_dev_origin_regex
)

# The dashboard calls this API directly from local dev and Railway.
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_origin_regex=cors_origin_regex,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(payments.router)
app.include_router(credentials.router)
app.include_router(treasury.router)
app.include_router(wallet.router)
app.include_router(agents_router)


def _cors_headers(request: Request) -> dict[str, str]:
    """CORS headers for an allowed origin (mirrors the CORSMiddleware policy)."""
    origin = request.headers.get("origin")
    if not origin:
        return {}
    allowed = origin in cors_origins or (
        bool(settings.cors_origin_regex) and re.fullmatch(settings.cors_origin_regex, origin) is not None
    )
    if not allowed:
        return {}
    return {"Access-Control-Allow-Origin": origin, "Vary": "Origin"}


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Return 500s *with* CORS headers.

    Starlette's ServerErrorMiddleware sits outside the CORS middleware, so an
    unhandled exception would otherwise reach the browser without an
    Access-Control-Allow-Origin header — surfacing as an opaque CORS error
    instead of the real failure. Adding the header here makes errors visible.
    """
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc)},
        headers=_cors_headers(request),
    )
