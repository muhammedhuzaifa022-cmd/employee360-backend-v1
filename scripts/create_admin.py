"""
Create the FIRST admin account (or any extra admin) from the command line.

Run from the project folder:
    python -m scripts.create_admin

The password is typed invisibly and stored ONLY as an Argon2 hash.
"""
import argparse
import getpass
import sys

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import func, select

from app.core.security import hash_password, validate_password_strength
from app.db.session import SessionLocal
from app.models import Department, User
from app.models.enums import UserRole


def ask(prompt: str, given: str | None) -> str:
    value = (given or input(prompt)).strip()
    if not value:
        sys.exit(f"Error: {prompt.strip(': ')} is required")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description="Create an Employee360 admin user")
    parser.add_argument("--name")
    parser.add_argument("--email")
    parser.add_argument("--department", default="Management")
    args = parser.parse_args()

    name = ask("Full name: ", args.name)
    try:
        email = validate_email(ask("Email: ", args.email), check_deliverability=False).normalized.lower()
    except EmailNotValidError as exc:
        sys.exit(f"Error: {exc}")

    password = getpass.getpass("Password (hidden): ")
    try:
        validate_password_strength(password)
    except ValueError as exc:
        sys.exit(f"Error: {exc}")
    if getpass.getpass("Repeat password: ") != password:
        sys.exit("Error: passwords do not match")

    with SessionLocal() as db:
        if db.scalar(select(User).where(func.lower(User.email) == email)):
            sys.exit(f"Error: a user with email {email} already exists")

        dept = db.scalar(select(Department).where(func.lower(Department.name) == args.department.lower()))
        if dept is None:
            dept = Department(name=args.department)
            db.add(dept)
            db.flush()

        user = User(full_name=name, email=email, hashed_password=hash_password(password),
                    role=UserRole.ADMIN, designation="Administrator", department_id=dept.id)
        db.add(user)
        db.commit()
        print(f"Admin created: {user.full_name} <{user.email}> (id {user.id})")


if __name__ == "__main__":
    main()
