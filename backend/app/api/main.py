from fastapi import APIRouter

from app.api.routes import employees

api_router = APIRouter()
api_router.include_router(employees.router)
