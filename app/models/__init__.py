"""
Imports every model so SQLAlchemy and Alembic know about all tables.
Always import models from here:  from app.models import User, Task
"""
from app.db.base import Base
from app.models.holiday import Holiday
from app.models.auth import DevicePushToken, RefreshToken
from app.models.department import Department
from app.models.leave import LeaveRequest
from app.models.notification import Notification
from app.models.project import Project, project_members
from app.models.task import Task, TaskComment, TaskHistory
from app.models.user import User
from app.models.report import DailyReport
from app.models.attendance import Attendance 
__all__ = [
    "Base", "Department", "User", "Project", "project_members", "Task",
    "TaskComment", "TaskHistory", "LeaveRequest", "Notification",
    "RefreshToken", "DevicePushToken",
]
