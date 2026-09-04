from fastapi import APIRouter

from app.api.routes import employees, job_types

api_router = APIRouter()
api_router.include_router(employees.router)
api_router.include_router(job_types.router)
