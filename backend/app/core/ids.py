"""
Path-parameter identifier validation.

Every identifier that ends up in a filesystem path (project_id, standard_key,
subargument_id, exhibit_id, section, version_id, ...) must match SAFE_ID.
Anything else is rejected with 404 -- not 400 -- so that callers cannot
distinguish "malformed" from "does not exist" (see Doc/01 M0).

Two layers of defence:
  1. `validate_path_params` -- a router-level dependency that checks *every*
     path parameter of the matched route. Attach it once per APIRouter.
  2. `storage.get_project_dir()` -- containment check on the resolved path.
"""

import re

from fastapi import HTTPException, Request

# 1-128 chars, must start alphanumeric, then alphanumeric / underscore / hyphen.
# Rejects '.', '/', '\\', whitespace, percent-encoded sequences, etc.
SAFE_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,127}$"
SAFE_ID = re.compile(SAFE_ID_PATTERN)


def is_safe_id(value: str) -> bool:
    return isinstance(value, str) and bool(SAFE_ID.match(value))


def validate_id(value: str, name: str = "id") -> str:
    """Return `value` unchanged if it is a safe identifier, else raise 404."""
    if not is_safe_id(value):
        raise HTTPException(status_code=404, detail=f"{name} not found")
    return value


async def validate_path_params(request: Request) -> None:
    """FastAPI dependency: validate all path params of the current route.

    Usage: APIRouter(prefix=..., dependencies=[Depends(validate_path_params)])
    """
    for name, value in request.path_params.items():
        validate_id(str(value), name)
