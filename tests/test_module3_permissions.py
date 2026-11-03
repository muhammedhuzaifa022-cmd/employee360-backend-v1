"""Module 3 tests: the role + department permission rules."""
import pytest
from sqlalchemy import select

from app.api.deps import require_roles
from app.core.exceptions import ForbiddenError
from app.models import User
from app.models.enums import UserRole
from app.services import permissions as P
from tests.factories import user


@pytest.fixture()
def people(db):
    return {
        "admin": user(db, "admin@c.com", UserRole.ADMIN, "Management"),
        "admin2": user(db, "admin2@c.com", UserRole.ADMIN, "Management"),
        "lead_eng": user(db, "lead.eng@c.com", UserRole.TEAMLEAD, "Engineering"),
        "lead_eng2": user(db, "lead.eng2@c.com", UserRole.TEAMLEAD, "Engineering"),
        "lead_des": user(db, "lead.des@c.com", UserRole.TEAMLEAD, "Design"),
        "emp_eng": user(db, "emp.eng@c.com", UserRole.EMPLOYEE, "Engineering"),
        "emp_eng2": user(db, "emp.eng2@c.com", UserRole.EMPLOYEE, "Engineering"),
        "emp_des": user(db, "emp.des@c.com", UserRole.EMPLOYEE, "Design"),
        "inactive_eng": user(db, "gone@c.com", UserRole.EMPLOYEE, "Engineering", active=False),
    }


def test_admin_manages_whole_company_but_not_self(people):
    a = people["admin"]
    for key in ["lead_eng", "lead_des", "emp_eng", "emp_des", "admin2"]:
        assert P.can_manage_user(a, people[key]), key
    assert not P.can_manage_user(a, a)


def test_team_lead_manages_only_employees_in_own_department(people):
    lead = people["lead_eng"]
    assert P.can_manage_user(lead, people["emp_eng"])
    assert P.can_manage_user(lead, people["emp_eng2"])
    assert not P.can_manage_user(lead, people["emp_des"])     # other department
    assert not P.can_manage_user(lead, people["lead_eng2"])   # a peer team lead
    assert not P.can_manage_user(lead, people["admin"])
    assert not P.can_manage_user(lead, lead)


def test_employee_manages_nobody(people):
    e = people["emp_eng"]
    assert not any(P.can_manage_user(e, people[k]) for k in people)


def test_view_rules(people):
    lead = people["lead_eng"]
    assert P.can_view_user(lead, people["emp_eng"]) and P.can_view_user(lead, people["lead_eng2"])
    assert not P.can_view_user(lead, people["emp_des"])
    e = people["emp_eng"]
    assert P.can_view_user(e, e) and not P.can_view_user(e, people["emp_eng2"])
    assert P.can_view_user(people["admin"], people["emp_des"])


def test_task_assignment_rules(people):
    lead, admin = people["lead_eng"], people["admin"]
    assert P.can_assign_task_to(lead, people["emp_eng"])
    assert P.can_assign_task_to(lead, lead)                    # own task
    assert not P.can_assign_task_to(lead, people["emp_des"])
    assert not P.can_assign_task_to(lead, people["inactive_eng"])
    assert not P.can_assign_task_to(admin, people["admin2"])   # tasks never go to admins
    assert P.can_assign_task_to(admin, people["lead_des"])
    assert not P.can_assign_task_to(people["emp_eng"], people["emp_eng"])


def test_leave_decision_rules(people):
    assert P.can_decide_leave(people["lead_eng"], people["emp_eng"])
    assert not P.can_decide_leave(people["lead_eng"], people["emp_des"])
    assert not P.can_decide_leave(people["lead_eng"], people["lead_eng2"])  # TL leave -> admin
    assert P.can_decide_leave(people["admin"], people["lead_eng"])
    assert P.can_decide_leave(people["admin"], people["admin2"])            # admin -> other admin
    assert not P.can_decide_leave(people["admin"], people["admin"])
    assert not P.can_decide_leave(people["emp_eng"], people["emp_eng2"])


def test_visible_users_filter(db, people):
    def visible(actor):
        return {u.email for u in db.scalars(select(User).where(P.visible_users_condition(actor)))}

    assert visible(people["emp_eng"]) == {"emp.eng@c.com"}
    eng = visible(people["lead_eng"])
    assert "emp.des@c.com" not in eng and "admin@c.com" not in eng
    assert {"emp.eng@c.com", "emp.eng2@c.com", "lead.eng2@c.com", "gone@c.com"} <= eng
    assert {"emp.des@c.com", "lead.des@c.com"} <= visible(people["admin"])


def test_managed_users_filter(db, people):
    managed = {u.email for u in db.scalars(
        select(User).where(P.managed_users_condition(people["lead_eng"])))}
    assert managed == {"emp.eng@c.com", "emp.eng2@c.com", "gone@c.com"}
    assert not list(db.scalars(select(User).where(P.managed_users_condition(people["emp_eng"]))))


def test_require_roles_dependency(people):
    only_admin = require_roles(UserRole.ADMIN)
    assert only_admin(people["admin"]) is people["admin"]
    with pytest.raises(ForbiddenError):
        only_admin(people["lead_eng"])
    managers = require_roles(UserRole.ADMIN, UserRole.TEAMLEAD)
    assert managers(people["lead_des"]) is people["lead_des"]
    with pytest.raises(ForbiddenError):
        managers(people["emp_eng"])
