from __future__ import annotations


class AppError(Exception):
    def __init__(self, code: str, status_code: int, message: str, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.message = message
        self.details = details or {}


class AmbiguousLocationError(AppError):
    def __init__(self, field_name: str, candidates: list[dict]):
        super().__init__(
            code="AMBIGUOUS_LOCATION",
            status_code=409,
            message=f"{field_name} is ambiguous. Please choose one of the suggested locations.",
            details={"field": field_name, "candidates": candidates},
        )


class ForbiddenError(AppError):
    def __init__(self):
        super().__init__("FORBIDDEN", 403, "You do not have access to this trip.")


class NotFoundError(AppError):
    def __init__(self, resource_name: str):
        super().__init__("NOT_FOUND", 404, f"{resource_name} was not found.")


class VersionConflictError(AppError):
    def __init__(self):
        super().__init__(
            "VERSION_CONFLICT",
            409,
            "Plan version or state has changed. Reload the latest plan before deciding.",
        )


class UnauthorizedActionError(AppError):
    def __init__(self):
        super().__init__("UNAUTHORIZED_ACTION", 403, "Only the trip owner can decide this plan.")
