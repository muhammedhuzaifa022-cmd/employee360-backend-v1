"""
Departments endpoints.

  GET    /departments          admin: all | team lead & employee: own department
  POST   /departments          create            (admin)
  PATCH  /departments/{id}     rename            (admin)
  DELETE /departments/{id}     delete if empty   (admin)
"""
from fastapi import APIRouter, Response, status

from app.api.deps import AdminUser, CurrentUser, DbSession
from app.schemas.user import DepartmentCreate, DepartmentOut, DepartmentUpdate, DepartmentWithCount
from app.services import department_service

router = APIRouter(prefix="/departments", tags=["Departments"])


@router.get("", response_model=list[DepartmentWithCount], summary="List departments")
def list_departments(user: CurrentUser, db: DbSession):
    return department_service.list_visible(db, user)


@router.post("", response_model=DepartmentOut, status_code=status.HTTP_201_CREATED,
             summary="Create department (admin)")
def create_department(body: DepartmentCreate, admin: AdminUser, db: DbSession):
    return department_service.create(db, body.name)


@router.patch("/{department_id}", response_model=DepartmentOut, summary="Rename department (admin)")
def rename_department(department_id: int, body: DepartmentUpdate, admin: AdminUser, db: DbSession):
    return department_service.rename(db, department_id, body.name)


@router.delete("/{department_id}", status_code=status.HTTP_204_NO_CONTENT,
               summary="Delete an empty department (admin)")
def delete_department(department_id: int, admin: AdminUser, db: DbSession):
    department_service.delete(db, department_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
