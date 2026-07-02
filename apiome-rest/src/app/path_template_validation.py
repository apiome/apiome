"""Validate OpenAPI path templates (pathname) for version_path rows."""

import re

_PARAM_RE = re.compile(r"\{([^}]*)\}")


def validate_openapi_path_template(pathname: str) -> None:
    """
    Raise ValueError with a readable message if pathname is not a valid template.

    Rules: non-empty after strip, must start with /, balanced {}, non-empty parameter
    names, unique parameter names.
    """
    if pathname is None:
        raise ValueError("Path cannot be empty.")

    s = pathname.strip()
    if len(s) == 0:
        raise ValueError("Path cannot be empty.")
    if s[0] != "/":
        raise ValueError("Path must start with /.")
    if re.search(r"\{\s*\}", s):
        raise ValueError("Path parameters cannot be empty (use a name inside braces, e.g. {id}).")

    depth = 0
    for ch in s:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        if depth < 0:
            raise ValueError("Invalid order of braces in the path template.")
    if depth != 0:
        raise ValueError("Curly braces { } are not balanced.")

    names = _PARAM_RE.findall(s)
    seen = set()
    for raw in names:
        name = raw.strip()
        if len(name) == 0:
            raise ValueError("Path parameter names cannot be empty.")
        if name in seen:
            raise ValueError(
                f"Duplicate path parameter name: {{{name}}}. Each template variable must be unique."
            )
        seen.add(name)
