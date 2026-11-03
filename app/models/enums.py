"""
Fixed lists of allowed values.

The text values are EXACTLY the same as in the frontend
(for example "Submitted for Review"), so the web page needs no changes.
"""
from enum import Enum


class UserRole(str, Enum):
    ADMIN = "admin"
    TEAMLEAD = "teamlead"
    EMPLOYEE = "employee"


class TaskStatus(str, Enum):
    NOT_STARTED = "Not Started"
    IN_PROGRESS = "In Progress"
    SUBMITTED = "Submitted for Review"
    COMPLETED = "Completed"
    DELAYED = "Delayed"
    ON_HOLD = "On Hold"


# Statuses an assignee may set on their own task (the frontend dropdown)
EMPLOYEE_SETTABLE_STATUSES = [
    TaskStatus.NOT_STARTED,
    TaskStatus.IN_PROGRESS,
    TaskStatus.ON_HOLD,
    TaskStatus.DELAYED,
]


class Priority(str, Enum):
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


class LeaveType(str, Enum):
    ANNUAL = "Annual"
    SICK = "Sick"
    CASUAL = "Casual"
    UNPAID = "Unpaid"


class LeaveStatus(str, Enum):
    PENDING = "Pending"
    APPROVED = "Approved"
    REJECTED = "Rejected"
    CANCELLED = "Cancelled"


class Platform(str, Enum):
    WEB = "web"
    ANDROID = "android"
    IOS = "ios"


class NotificationCategory(str, Enum):
    """
    What a notification is about. Stored as plain text (no DB change needed
    to add new ones). The mobile app can pick an icon / screen from this.
    """
    TASK_ASSIGNED = "task_assigned"
    TASK_SUBMITTED = "task_submitted"
    TASK_APPROVED = "task_approved"
    TASK_REJECTED = "task_rejected"
    TASK_RESCHEDULED = "task_rescheduled"
    TASK_DEADLINE_CHANGED = "task_deadline_changed"
    TASK_COMMENT = "task_comment"
    LEAVE_REQUESTED = "leave_requested"
    LEAVE_APPROVED = "leave_approved"
    LEAVE_REJECTED = "leave_rejected"
    LEAVE_CANCELLED = "leave_cancelled"
    PROJECT_ADDED = "project_added"
    ACCOUNT = "account"
    GENERAL = "general"
