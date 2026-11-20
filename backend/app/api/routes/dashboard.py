from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import DB, current_user
from app.models import User
from app.services.call_query import CallFilters, filters_dep
from app.services.dashboard import build_dashboard

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard")
def dashboard(f: CallFilters = Depends(filters_dep), _: User = Depends(current_user), db: Session = DB):
    return build_dashboard(db, f)
