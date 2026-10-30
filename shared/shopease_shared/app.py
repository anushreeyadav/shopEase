"""Wires the common middleware and error handlers into a service's FastAPI app."""

from fastapi import FastAPI

from shopease_shared.errors import install_error_handlers
from shopease_shared.request_id import RequestIDMiddleware


def install_common(app: FastAPI) -> None:
    install_error_handlers(app)
    app.add_middleware(RequestIDMiddleware)
