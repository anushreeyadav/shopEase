"""Domain errors raised by the services. No HTTP code here.

app/main.py turns each into a JSON response: NotFoundError -> 404, ConflictError -> 409,
InvalidFieldError -> 422 (in the same shape as request validation errors).
Every message is a fixed, client-safe sentence; none contains submitted values.
"""


class ServiceError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class NotFoundError(ServiceError):
    """The addressed record does not exist, or is inactive and the caller may not see it."""


class ConflictError(ServiceError):
    """The request clashes with the current state: a duplicate, a record in use, or too little stock."""


class InvalidFieldError(ServiceError):
    """A field's value cannot be used: it refers to a missing record, or breaks a rule that
    involves stored data (for example a discount that is not below the stored price)."""

    def __init__(self, field: str, message: str):
        super().__init__(message)
        self.field = field
