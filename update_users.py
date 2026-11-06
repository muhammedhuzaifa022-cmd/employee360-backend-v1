
from app.db.session import SessionLocal
from app.models.user import User
from app.models.department import Department
from app.models.leave import LeaveRequest


def fix_leave():
    db = SessionLocal()

    try:
        # 1. Find AI Department
        ai_dept = (
            db.query(Department)
            .filter(Department.name == "AI")
            .first()
        )

        if not ai_dept:
            print("AI Department not found.")
            return

        # 2. Find Abdul Rauf and Huzaifa
        rauf = (
            db.query(User)
            .filter(User.email == "rauf@company.com")
            .first()
        )

        huzaifa = (
            db.query(User)
            .filter(User.email == "huzaifa@company.com")
            .first()
        )

        if not rauf:
            print("Abdul Rauf not found.")
            return

        if not huzaifa:
            print("Huzaifa not found.")
            return

        # 3. Assign users to AI Department
        rauf.department_id = ai_dept.id
        huzaifa.department_id = ai_dept.id

        # 4. Find Huzaifa's latest leave request
        latest_leave = (
            db.query(LeaveRequest)
            .filter(LeaveRequest.employee_id == huzaifa.id)
            .order_by(LeaveRequest.id.desc())
            .first()
        )

        if latest_leave:
            latest_leave.status = "Pending"
            print("Huzaifa's leave request status reset to Pending.")
        else:
            print("No leave request found for Huzaifa.")

        # 5. Save changes
        db.commit()

        print("Successfully updated Huzaifa and Abdul Rauf's department.")

    except Exception as e:
        db.rollback()
        print(f"Error occurred: {e}")

    finally:
        db.close()


if __name__ == "__main__":
    fix_leave()
