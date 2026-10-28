"""Cap'n Proto identifier rules for the ``.capnp`` emitter — MFX-30.2 (#4179).

The Cap'n Proto compiler rejects a schema whose names break its style rules, so a model converted
from OpenAPI (``first_name``, ``HTTP-Error``, ``in-stock``) must be renamed before it compiles:

* type names (``struct``, ``enum``, ``interface``, ``using``) begin with a capital letter;
* every other name (fields, enumerants, methods, parameters) begins with a lower-case letter;
* no name contains an underscore — ``capnp`` asks for camelCase.

:func:`type_identifier` and :func:`member_identifier` apply those rules; :class:`NameScope` keeps
the renamed identifiers unique inside one scope (two sources that both become ``firstName``).
"""

from __future__ import annotations

import re
from typing import List, Set

__all__ = ["BUILTIN_TYPE_NAMES", "NameScope", "member_identifier", "type_identifier"]

#: Cap'n Proto's built-in type names. A user type named one of these would shadow the built-in
#: for every field in the file, so :func:`type_identifier` renames it (``Text`` → ``TextType``).
BUILTIN_TYPE_NAMES = frozenset(
    {
        "Void",
        "Bool",
        "Int8",
        "Int16",
        "Int32",
        "Int64",
        "UInt8",
        "UInt16",
        "UInt32",
        "UInt64",
        "Float32",
        "Float64",
        "Text",
        "Data",
        "List",
        "AnyPointer",
        "AnyStruct",
        "AnyList",
        "Capability",
    }
)

_WORD = re.compile(r"[A-Za-z0-9]+")


def _words(raw: str) -> List[str]:
    """Split ``raw`` on every character that is not an ASCII letter or digit."""
    return _WORD.findall(raw or "")


def _capitalize(word: str) -> str:
    """Start a camelCase word: ``pet`` → ``Pet``, ``UNSPECIFIED`` → ``Unspecified``.

    A word written all in capitals (a ``SCREAMING_SNAKE`` part) is title-cased; any other word keeps
    its own casing after the first letter (``iPhone`` → ``IPhone``).
    """
    if len(word) > 1 and word.isupper():
        return word.capitalize()
    return word[:1].upper() + word[1:]


def _lower_leading(word: str) -> str:
    """Lower-case the leading capitals of ``word`` the way camelCase reads.

    ``Name`` → ``name``, ``ID`` → ``id``, ``HTTPCode`` → ``httpCode`` (the last capital of a run
    that is followed by a lower-case letter starts the next word).
    """
    run = len(word) - len(word.lstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ"))
    if run == 0:
        return word
    if run == len(word):
        return word.lower()
    if run == 1:
        return word[0].lower() + word[1:]
    return word[: run - 1].lower() + word[run - 1 :]


def type_identifier(raw: str, *, fallback: str = "Type") -> str:
    """Return ``raw`` as a legal Cap'n Proto type name.

    Args:
        raw: The source name, e.g. ``pet_store`` or ``HTTP-Error``.
        fallback: Used when ``raw`` has no letters or digits at all.

    Returns:
        A PascalCase name that starts with a capital letter, has no underscore and is not a
        built-in type name: ``pet_store`` → ``PetStore``, ``HTTP_ERROR`` → ``HttpError``,
        ``2xx`` → ``T2xx``, ``Text`` → ``TextType``.
    """
    words = _words(raw)
    if not words:
        return fallback
    name = "".join(_capitalize(word) for word in words)
    if name[0].isdigit():
        name = f"T{name}"
    if name in BUILTIN_TYPE_NAMES:
        name = f"{name}Type"
    return name


def member_identifier(raw: str, *, fallback: str = "field") -> str:
    """Return ``raw`` as a legal Cap'n Proto field, enumerant, method or parameter name.

    Args:
        raw: The source name, e.g. ``first_name``, ``ACTIVE`` or ``in-stock``.
        fallback: Used when ``raw`` has no letters or digits at all.

    Returns:
        A camelCase name that starts with a lower-case letter and has no underscore:
        ``first_name`` → ``firstName``, ``ACTIVE`` → ``active``, ``STATUS_UNSPECIFIED`` →
        ``statusUnspecified``, ``X-Request-ID`` → ``xRequestId``, ``2xx`` → ``v2xx``.
    """
    words = _words(raw)
    if not words:
        return fallback
    name = _lower_leading(words[0]) + "".join(_capitalize(word) for word in words[1:])
    if name[0].isdigit():
        name = f"v{name}"
    return name


class NameScope:
    """The identifiers already used in one Cap'n Proto scope (a file, struct, enum or method).

    Cap'n Proto refuses two declarations with the same name in a scope. Renaming can create such a
    pair (``first_name`` and ``firstName``), so each later claimant gets a numeric suffix.
    """

    def __init__(self) -> None:
        self._taken: Set[str] = set()

    def claim(self, name: str) -> str:
        """Reserve ``name`` in this scope and return it, suffixed (``name2``, …) if already taken.

        Args:
            name: A legal identifier (from :func:`type_identifier` or :func:`member_identifier`).

        Returns:
            The identifier actually reserved.
        """
        candidate = name
        suffix = 2
        while candidate in self._taken:
            candidate = f"{name}{suffix}"
            suffix += 1
        self._taken.add(candidate)
        return candidate
