from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes import health, payments

app = FastAPI(title="Treasury Agent API", version="0.1.0")

# The dashboard (Vite dev server) and any local origin call this API directly.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:4173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(payments.router)
