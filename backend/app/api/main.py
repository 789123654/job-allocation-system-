from fastapi import APIRouter

from app.api.routes import employees, issues, job_types, notifications, tasks

api_router = APIRouter()
api_router.include_router(employees.router)
api_router.include_router(job_types.router)
api_router.include_router(tasks.router)
api_router.include_router(issues.router)
api_router.include_router(notifications.router)
