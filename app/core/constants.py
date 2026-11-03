"""
Business constants taken directly from the existing frontend,
so web and mobile show exactly the same numbers.
"""

# Workload page: "Open hours against a 40-hour week"
WEEKLY_CAPACITY_HOURS = 40
BUSY_THRESHOLD_HOURS = 30  # more than 30h = Busy, more than 40h = Overloaded

# Performance page: Completion x 50% + Deadlines x 30% + Manager rating x 20%
PERFORMANCE_WEIGHTS = {
    "completion": 0.5,
    "deadlines": 0.3,
    "manager_rating": 0.2,
}

# Approve-task slider in the frontend
RATING_MIN = 0
RATING_MAX = 100
DEFAULT_RATING = 85

# Lists (pagination) - small pages are friendly to mobile apps
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

# Password rules (enforced from Module 3)
PASSWORD_MIN_LENGTH = 8
