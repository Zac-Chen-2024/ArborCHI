"""
Application error types + unified error response schema.

Raise these from services; main.py maps them to HTTP responses so routers
do not need try/except boilerplate:

    ConfigError   -> 400  (e.g. requested LLM provider has no API key)
    NotFoundError -> 404
"""

from typing import Any, Optional

from pydantic import BaseModel


class ErrorResponse(BaseModel):
    success: bool = False
    error: str
    detail: Optional[Any] = None


class AppError(Exception):
    """Base for errors that are safe to show to the client verbatim."""

    status_code = 500

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class ConfigError(AppError):
    status_code = 400


class NotFoundError(AppError):
    status_code = 404
