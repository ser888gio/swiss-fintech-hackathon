from fastapi import APIRouter

from ..config import get_settings
from ..xrpl_client import network_label

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str | bool]:
    settings = get_settings()
    return {
        "status": "ok",
        "network": network_label(settings.xrpl_endpoint),
        "fireflyConfirmationEnabled": settings.firefly_confirmation_enabled,
    }
