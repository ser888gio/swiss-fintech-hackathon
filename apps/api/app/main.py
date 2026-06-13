from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .routes import health, payments

app = FastAPI(title="Treasury Agent API", version="0.1.0")
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

# The dashboard calls this API directly from local dev and Railway.
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_origin_regex=settings.cors_origin_regex,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(payments.router)
