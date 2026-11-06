
from app.db.session import SessionLocal
from app.models.user import User

from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

from sqlalchemy import text

password_hash = PasswordHash((Argon2Hasher(),))


def clean_and_update_users():

    db = SessionLocal()

    try:

        # 1. Users to keep and update
        updates = [
            {
                "old_email": "aisha@company.com",
                "new_name": "Abdul Waheed",
                "new_email": "waheed@company.com",
                "password": "abdulwaheedisboss@123",
                "role": "admin",
                "desig": "Administrator"
            },
            {
                "old_email": "fatima@company.com",
                "new_name": "Abdul Rauf",
                "new_email": "rauf@company.com",
                "password": "abdulraufbhai@123",
                "role": "teamlead",
                "desig": "Team Lead"
            },
            {
                "old_email": "rahul@company.com",
                "new_name": "Abdul Quddus",
                "new_email": "quddus@company.com",
                "password": "abdulquddusbhai@123",
                "role": "teamlead",
                "desig": "Team Lead"
            },
            {
                "old_email": "neha@company.com",
                "new_name": "Rehmat",
                "new_email": "rehmat@company.com",
                "password": "r@hmat@123",
                "role": "admin",
                "desig": "HR Manager"
            },
            {
                "old_email": "mohammed@company.com",
                "new_name": "Huzaifa",
                "new_email": "huzaifa@company.com",
                "password": "huzaifa@123",
                "role": "employee",
                "desig": "Associate"
            },
            {
                "old_email": "priya@company.com",
                "new_name": "Ammar",
                "new_email": "ammar@company.com",
                "password": "ammar@123",
                "role": "employee",
                "desig": "Associate"
            }
        ]

        old_emails = [u["old_email"] for u in updates]
        new_emails = [u["new_email"] for u in updates]

        # 2. Validate email addresses
        if len(new_emails) != len(set(new_emails)):
            raise Exception("Duplicate new email addresses found!")

        # 3. Find all six original users
        existing_users = (
            db.query(User)
            .filter(User.email.in_(old_emails))
            .all()
        )

        if len(existing_users) != 6:
            raise Exception(
                f"Expected 6 users, found {len(existing_users)}. "
                "Cleanup cancelled."
            )

        # 4. Check email conflicts
        existing_ids = {u.id for u in existing_users}

        conflicts = (
            db.query(User)
            .filter(User.email.in_(new_emails))
            .all()
        )

        for user in conflicts:
            if user.id not in existing_ids:
                raise Exception(
                    f"Email already exists: {user.email}"
                )

        # 5. Update six users
        for data in updates:

            user = next(
                u for u in existing_users
                if u.email == data["old_email"]
            )

            user.full_name = data["new_name"]
            user.email = data["new_email"]
            user.hashed_password = password_hash.hash(
                data["password"]
            )
            user.role = data["role"]
            user.designation = data["desig"]

            print(
                f"Updated: {data['new_name']} "
                f"({data['new_email']})"
            )

        db.flush()

        # 6. Find extra users
        all_users = db.query(User).all()

        extra_users = [
            user for user in all_users
            if user.email not in new_emails
        ]

        # 7. Delete related records
        for user in extra_users:

            uid = user.id

            print(f"Cleaning data for: {user.email}")

            # Delete tasks
            db.execute(
                text("""
                    DELETE FROM tasks
                    WHERE assignee_id = :uid
                    OR assigned_by_id = :uid
                """),
                {"uid": uid}
            )

            # Delete leave requests
            db.execute(
                text("""
                    DELETE FROM leave_requests
                    WHERE employee_id = :uid
                    OR decided_by_id = :uid
                """),
                {"uid": uid}
            )

            # Delete daily reports
            db.execute(
                text("""
                    DELETE FROM daily_reports
                    WHERE employee_id = :uid
                """),
                {"uid": uid}
            )

            # Delete attendance
            db.execute(
                text("""
                    DELETE FROM attendance
                    WHERE employee_id = :uid
                """),
                {"uid": uid}
            )

            # Delete notifications
            db.execute(
                text("""
                    DELETE FROM notifications
                    WHERE recipient_id = :uid
                """),
                {"uid": uid}
            )

            # Delete projects managed by this user
            # WARNING: This also deletes those projects.
            db.execute(
                text("""
                    DELETE FROM projects
                    WHERE manager_id = :uid
                """),
                {"uid": uid}
            )

            # Delete extra user
            db.delete(user)

            print(f"Deleted user: {user.email}")

        # 8. Commit everything together
        db.commit()

        print("\nSUCCESS!")
        print("Six users updated.")
        print(f"{len(extra_users)} extra users deleted.")
        print("Database cleanup completed successfully!")

    except Exception as e:

        db.rollback()

        print("\nERROR:", str(e))
        print("All database changes have been rolled back.")

    finally:
        db.close()


# 9. Execute script
if __name__ == "__main__":
    clean_and_update_users()
