"""Public, read-only view of the configured shared treasury wallet."""

from fastapi import APIRouter, HTTPException

from ..schemas import WalletOverview
from ..tools import wallet as wallet_tool

router = APIRouter(prefix="/wallet", tags=["wallet"])


@router.get("", response_model=WalletOverview)
async def get_wallet() -> WalletOverview:
    try:
        return await wallet_tool.get_overview()
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
