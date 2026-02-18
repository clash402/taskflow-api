from __future__ import annotations

from fastapi import APIRouter

from src.utils.time import utc_now_iso

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "time": utc_now_iso()}
