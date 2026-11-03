"""
WHO MAY DO WHAT - the single place for role and department rules.

  Admin     : the whole company.
  Team lead : only their OWN department (and only employees in it).
  Employee  : only themselves.

Every later module (users, tasks, leave, analytics...) uses these functions,
so the rules are the same for the web app and the mobile apps.
"""
from sqlalchemy import ColumnElement, exists, false, select, true

from app.models import Project, Task, User, project_members
from app.models.enums import UserRole


def is_admin(user: User) -> bool:
    return user.role == UserRole.ADMIN


def is_team_lead(user: User) -> bool:
    return user.role == UserRole.TEAMLEAD


def is_manager(user: User) -> bool:
    """Admins and team leads (the frontend's canManage())."""
    return user.role in (UserRole.ADMIN, UserRole.TEAMLEAD)


def same_department(a: User, b: User) -> bool:
    return a.department_id is not None and a.department_id == b.department_id


# ---------------- people ----------------
def can_view_user(actor: User, target: User) -> bool:
    """Profile / Team page / performance of `target`."""
    if actor.id == target.id or is_admin(actor):
        return True
    if is_team_lead(actor):
        return same_department(actor, target)
    return False


def can_manage_user(actor: User, target: User) -> bool:
    """Approve their work and leave, change their deadlines, see their workload."""
    if actor.id == target.id:
        return False  # nobody approves their own work or leave
    if is_admin(actor):
        return True
    if is_team_lead(actor):
        return same_department(actor, target) and target.role == UserRole.EMPLOYEE
    return False


def can_assign_task_to(actor: User, target: User) -> bool:
    """Frontend rule: tasks go to active non-admin users."""
    if not target.is_active or target.role == UserRole.ADMIN:
        return False
    if is_admin(actor):
        return True
    if is_team_lead(actor):
        return target.id == actor.id or (same_department(actor, target)
                                         and target.role == UserRole.EMPLOYEE)
    return False


def can_decide_leave(actor: User, requester: User) -> bool:
    """
    Employee leave  -> team leads of that department, or any admin.
    Team lead leave -> admins only.
    Admin leave     -> another admin.
    Nobody decides their own leave.
    """
    return can_manage_user(actor, requester)


def can_administer_accounts(actor: User) -> bool:
    """Add employees, activate/deactivate, change roles."""
    return is_admin(actor)


# ---------------- tasks ----------------
def can_view_task(actor: User, task: Task) -> bool:
    """Admin: all. Team lead: tasks whose assignee is in their department. Employee: own."""
    if is_admin(actor) or task.assignee_id == actor.id:
        return True
    return is_team_lead(actor) and same_department(actor, task.assignee)


def can_manage_task(actor: User, task: Task) -> bool:
    """
    Edit details, change deadline, reschedule, reassign, delete.
    Admin: any task. Team lead: tasks of employees in their department, and their own.
    """
    if is_admin(actor):
        return True
    if not is_team_lead(actor):
        return False
    if task.assignee_id == actor.id:
        return True
    return same_department(actor, task.assignee) and task.assignee.role == UserRole.EMPLOYEE


def can_review_task(actor: User, task: Task) -> bool:
    """Approve / request changes. Never your own task (same rule as leave)."""
    return can_manage_user(actor, task.assignee)


def is_task_assignee(actor: User, task: Task) -> bool:
    return task.assignee_id == actor.id


# ---------------- projects ----------------
def can_view_project(actor: User, project: Project) -> bool:
    """
    Admin: all. Team lead: projects they manage or belong to, plus projects
    with any member from their department. Employee: projects they belong to.
    """
    if is_admin(actor) or project.manager_id == actor.id:
        return True
    if any(m.id == actor.id for m in project.members):
        return True
    if is_team_lead(actor) and actor.department_id is not None:
        return any(m.department_id == actor.department_id for m in project.members)
    return False


def can_create_project(actor: User) -> bool:
    return is_manager(actor)


def can_edit_project(actor: User, project: Project) -> bool:
    """Admin: any project. Team lead: only projects they manage."""
    return is_admin(actor) or (is_team_lead(actor) and project.manager_id == actor.id)


def can_be_project_manager(target: User) -> bool:
    return target.is_active and target.role in (UserRole.ADMIN, UserRole.TEAMLEAD)


def can_change_project_member(actor: User, target: User) -> bool:
    """
    Members are employees (same as the frontend form).
    Admin: any employee. Team lead: employees of their own department only.
    """
    if target.role != UserRole.EMPLOYEE:
        return False
    if is_admin(actor):
        return True
    return is_team_lead(actor) and same_department(actor, target)


# ---------------- database filters ----------------
def visible_users_condition(actor: User) -> ColumnElement[bool]:
    """WHERE-clause: which users `actor` may see in lists."""
    if is_admin(actor):
        return true()
    if is_team_lead(actor):
        if actor.department_id is None:
            return User.id == actor.id
        return User.department_id == actor.department_id
    return User.id == actor.id


def managed_users_condition(actor: User) -> ColumnElement[bool]:
    """WHERE-clause: users whose work/leave `actor` manages."""
    if is_admin(actor):
        return User.id != actor.id
    if is_team_lead(actor) and actor.department_id is not None:
        return (User.department_id == actor.department_id) & (User.role == UserRole.EMPLOYEE)
    return false()


def visible_projects_condition(actor: User) -> ColumnElement[bool]:
    """WHERE-clause version of can_view_project (for lists)."""
    if is_admin(actor):
        return true()
    pm = project_members
    is_member = exists(select(1).select_from(pm).where(
        pm.c.project_id == Project.id, pm.c.user_id == actor.id))
    cond = (Project.manager_id == actor.id) | is_member
    if is_team_lead(actor) and actor.department_id is not None:
        dept_member = exists(select(1).select_from(pm.join(User, User.id == pm.c.user_id)).where(
            pm.c.project_id == Project.id, User.department_id == actor.department_id))
        cond = cond | dept_member
    return cond


def visible_tasks_condition(actor: User) -> ColumnElement[bool]:
    """WHERE-clause version of can_view_task (for lists)."""
    if is_admin(actor):
        return true()
    if is_team_lead(actor) and actor.department_id is not None:
        dept_users = select(User.id).where(User.department_id == actor.department_id)
        return Task.assignee_id.in_(dept_users) | (Task.assignee_id == actor.id)
    return Task.assignee_id == actor.id
