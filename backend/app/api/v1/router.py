# app/api/v1/router.py
from fastapi import APIRouter
from app.api.v1.endpoints.health import router as health_router
from app.api.v1.endpoints.auth import router as auth_router
from app.api.v1.endpoints.files import router as upload_router
from app.api.v1.endpoints.spaces import router as space_router

api_v1_router = APIRouter()
api_v1_router.include_router(health_router, tags=["health"])
api_v1_router.include_router(auth_router, tags=["auth"])
api_v1_router.include_router(upload_router, tags=["upload"])
api_v1_router.include_router(space_router, tags=["space"])
