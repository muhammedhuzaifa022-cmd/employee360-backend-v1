"""
Joins every v1 router together under /api/v1.
New modules (projects, tasks...) are added here one by one.
"""
from fastapi import APIRouter
from app.api.v1 import leave, report
from app.api.v1 import leave, report, attendance
from app.api.v1 import auth, departments, devices, notifications, projects, system, tasks, users
from app.api.v1 import leave 
from app.api.v1 import holidays
api_router = APIRouter()
api_router.include_router(system.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(departments.router)
api_router.include_router(projects.router)
api_router.include_router(tasks.router)
api_router.include_router(notifications.router)
api_router.include_router(devices.router)
api_router.include_router(leave.router, tags=["Leave"])
api_router.include_router(report.router, tags=["Daily Reports"])
api_router.include_router(attendance.router, tags=["Attendance"])
api_router.include_router(holidays.router, prefix="/holidays", tags=["Holidays"])

