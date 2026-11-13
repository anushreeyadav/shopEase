"""Error responses documented in the OpenAPI schema, shared by the routers."""

from app.schemas.common_schema import ErrorResponse, ValidationErrorResponse

OPTIONAL_AUTH_ERRORS = {
    401: {"model": ErrorResponse, "description": "Token invalid or expired, or include_inactive without a token"},
    403: {"model": ErrorResponse, "description": "include_inactive needs the ADMIN role"},
    422: {"model": ValidationErrorResponse, "description": "Invalid query parameters"},
    503: {"model": ErrorResponse, "description": "Authentication Service or database unavailable"},
}
ADMIN_ERRORS = {
    401: {"model": ErrorResponse, "description": "Token missing, invalid, or expired"},
    403: {"model": ErrorResponse, "description": "Inactive user, or ADMIN role required"},
    503: {"model": ErrorResponse, "description": "Authentication Service or database unavailable"},
}
NOT_FOUND = {404: {"model": ErrorResponse, "description": "Not found"}}
CONFLICT = {409: {"model": ErrorResponse, "description": "Conflicts with existing data or stock levels"}}
INVALID = {422: {"model": ValidationErrorResponse, "description": "Invalid request data"}}
BAD_BODY = {400: {"model": ErrorResponse, "description": "Body is not a JSON object (malformed JSON, missing, or wrong "
                                                          "Content-Type)"}}
