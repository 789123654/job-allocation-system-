from fastapi import APIRouter

from app.api.routes import employees, job_types, tasks

api_router = APIRouter()
api_router.include_router(employees.router)
api_router.include_router(job_types.router)
api_router.include_router(tasks.router)
