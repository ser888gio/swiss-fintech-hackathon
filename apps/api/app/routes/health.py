from fastapi import APIRouter

from ..config import get_settings
from ..xrpl_client import network_label

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str | bool]:
    settings = get_settings()
    return {
        "status": "ok",
        "mockMode": settings.use_mock_xrpl,
        "network": network_label(
            settings.xrpl_endpoint,
            use_mock=settings.use_mock_xrpl,
        ),
        "fireflyConfirmationEnabled": settings.firefly_confirmation_enabled,
    }
