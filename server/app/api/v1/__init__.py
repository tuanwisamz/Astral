from fastapi import APIRouter

from app.api.v1 import admin, ai, incidents, map, meta, priority, reports, segments

router = APIRouter(prefix="/api/v1")
for module in (meta, map, segments, incidents, reports, priority, ai, admin):
    router.include_router(module.router)
