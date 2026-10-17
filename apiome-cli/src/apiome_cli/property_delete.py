"""What ``apiome properties delete`` says before and after it deletes (CLI 6.5, #3227).

The command reads the property's ``usage`` (the class attributes that use it, from the
single-property GET, apiome-rest 1.354.0+). Unused, it deletes after you type the name. In use, it
stops (exit 6) unless ``--force --yes``, which asks the server to remove those class attributes and
delete the property in one transaction (``DELETE …?force=true``, apiome-rest 1.356.0+). Published
versions cannot change, so a use there refuses the forced delete too. These functions hold the
wording, without HTTP.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from apiome_cli.property_show import usage_lines

#: Shown under the in-use list: how to proceed (the CLI has no command to detach one attribute).
IN_USE_HINT = (
    "Hint: remove the attribute from those classes in the Studio,\n"
    "      or pass --force --yes to remove them and delete the property in one step."
)


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" + ("" if count == 1 else "s")


def render_in_use(name: str, usage: Sequence[Mapping[str, Any]]) -> str:
    """The refusal for a property in use: the class attributes, one per line, then the hint."""
    lines = [f"✘ Property '{name}' is in use by {_plural(len(usage), 'class attribute')}:"]
    lines += [f"     {line}" for line in usage_lines(usage)]
    lines.append(IN_USE_HINT)
    return "\n".join(lines)


def render_force_plan(name: str, usage: Sequence[Mapping[str, Any]]) -> str:
    """What ``--force`` is about to do."""
    lines = [f"Removing '{name}' from {_plural(len(usage), 'class attribute')}, then deleting it:"]
    lines += [f"     {line}" for line in usage_lines(usage)]
    return "\n".join(lines)


def render_published_refusal(name: str, uses: Sequence[Mapping[str, Any]]) -> str:
    """The server's 409: uses in published versions, which cannot change."""
    lines = [f"✘ Property '{name}' is used in published versions, which cannot change; nothing was deleted:"]
    lines += [f"     {u.get('class_name')}.{u.get('attribute_name')}  (version {u.get('version')})" for u in uses]
    lines.append("Hint: remove it from those classes in a new draft version first.")
    return "\n".join(lines)


def render_deleted(name: str, detached: Any = None) -> str:
    """The success line; with ``--force``, how many class attributes were removed."""
    if isinstance(detached, int) and detached:
        return f"✔ Deleted property '{name}' and removed it from {_plural(detached, 'class attribute')}."
    return f"✔ Deleted property '{name}'."
