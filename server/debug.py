from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from server.config import settings
from server.repository import list_recent_contributions
from server.scoring_store import list_scoring_results


def require_debug_api_enabled() -> None:
    if settings.debug_api_enabled:
        return
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")


router = APIRouter(
    prefix="/debug",
    tags=["debug"],
    include_in_schema=False,
    dependencies=[Depends(require_debug_api_enabled)],
)


@router.get("/scoring-results")
def debug_scoring_results(limit: int = Query(default=20, ge=1, le=200)) -> dict[str, object]:
    return {
        "count": min(limit, len(list_scoring_results(limit))),
        "results": list_scoring_results(limit),
    }


@router.get("/contributions")
def debug_contributions(limit: int = Query(default=20, ge=1, le=200)) -> dict[str, object]:
    results = list_recent_contributions(limit)
    return {
        "count": len(results),
        "results": results,
    }
