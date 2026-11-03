"""
One error format for web AND mobile.

Every error the API returns looks like this:

    {
      "detail": "Human readable message",
      "code":   "MACHINE_READABLE_CODE",
      "fields": {"field_name": "what is wrong"}   # only for invalid input
    }

Apps can show `detail` directly, or translate using `code`.
"""
import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("employee360")


# ---------------------------------------------------------------
# Our own error types - services raise these, never raw HTTP errors
# ---------------------------------------------------------------
class AppError(Exception):
    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "BAD_REQUEST"
    detail: str = "Bad request"

    def __init__(self, detail: str | None = None, *, code: str | None = None,
                 fields: dict[str, str] | None = None, headers: dict[str, str] | None = None):
        self.detail = detail or self.detail
        self.code = code or self.code
        self.fields = fields
        self.headers = headers
        super().__init__(self.detail)


class BadRequestError(AppError):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "BAD_REQUEST"
    detail = "Bad request"


class UnauthorizedError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "UNAUTHORIZED"
    detail = "Not authenticated"


class ForbiddenError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "FORBIDDEN"
    detail = "You are not allowed to perform this action"


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "NOT_FOUND"
    detail = "Not found"


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "CONFLICT"
    detail = "Conflict"


class TooManyRequestsError(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "TOO_MANY_REQUESTS"
    detail = "Too many attempts. Please try again later."


class ValidationAppError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "VALIDATION_ERROR"
    detail = "Some fields are invalid"


# ---------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------
def error_body(detail: str, code: str, fields: dict | None = None) -> dict:
    return {"detail": detail, "code": code, "fields": fields}


HTTP_CODE_NAMES = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    415: "UNSUPPORTED_MEDIA_TYPE",
    422: "VALIDATION_ERROR",
    429: "TOO_MANY_REQUESTS",
}


# ---------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------
async def app_error_handler(request: Request, exc: AppError):
    headers = dict(exc.headers or {})
    if exc.status_code == 401:
        headers.setdefault("WWW-Authenticate", "Bearer")
    return JSONResponse(status_code=exc.status_code,
                        content=error_body(exc.detail, exc.code, exc.fields),
                        headers=headers or None)


async def http_error_handler(request: Request, exc: StarletteHTTPException):
    code = HTTP_CODE_NAMES.get(exc.status_code, "HTTP_ERROR")
    detail = exc.detail if isinstance(exc.detail, str) else code.replace("_", " ").capitalize()
    return JSONResponse(status_code=exc.status_code,
                        content=error_body(detail, code),
                        headers=getattr(exc, "headers", None))


async def validation_error_handler(request: Request, exc: RequestValidationError):
    fields: dict[str, str] = {}
    for err in exc.errors():
        # loc looks like ("body", "email") -> "email"
        loc = [str(p) for p in err.get("loc", []) if p not in ("body", "query", "path", "header")]
        key = ".".join(loc) or "request"
        msg = str(err.get("msg", "Invalid value")).removeprefix("Value error, ")
        fields.setdefault(key, msg)
    return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                        content=error_body("Some fields are invalid", "VALIDATION_ERROR", fields))


async def unhandled_error_handler(request: Request, exc: Exception):
    # Full details go to the server log only - never to the user.
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        content=error_body("Something went wrong on the server", "INTERNAL_ERROR"))


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
