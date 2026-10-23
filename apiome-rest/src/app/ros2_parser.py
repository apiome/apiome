"""ROS 2 interface reader — FMT-9.3 (#5470).

Reads the three ROS 2 interface definition files, which share one line grammar:

* ``.msg`` — one section of fields and constants (a message);
* ``.srv`` — a request and a response section separated by a ``---`` line (a service);
* ``.action`` — goal, result and feedback sections separated by two ``---`` lines (an action).

Each non-blank, non-comment line is either a **field** or a **constant**::

    <type> <field_name> [<default value>]
    <type> <CONSTANT_NAME>=<value>

where ``<type>`` is a primitive (``bool byte char int8 … uint64 float32 float64 string wstring``),
a message of the same package by bare name (``LoadCell``) or a message of another package
(``geometry_msgs/Pose``, also ``geometry_msgs/msg/Pose``); a string may carry an upper bound
(``string<=32``) and any type may be an array — unbounded (``T[]``), fixed-size (``T[3]``) or bounded
(``T[<=10]``). ``#`` starts a comment; comments directly above a field (or after it on the same line)
document it, and the comment block at the top of a file documents the interface.

A **package fileset** (an interface package as an archive: ``package.xml`` beside ``msg/``,
``srv/`` and ``action/`` directories, or just the interface files) is read whole, so a reference
resolves against every interface in the import:

* a **bare name** names a message of the same package. In a fileset it must be one of the
  package's own interfaces; in a single uploaded file the package's other files were not supplied,
  so it is kept as a *declared unresolved* sibling reference.
* a **package-qualified name** resolves to the fileset's own interface when that package is in the
  import. A package outside the import is a *declared unresolved* external reference when it is a
  standard ROS 2 interface package (:data:`STANDARD_INTERFACE_PACKAGES`) or a dependency the
  package's ``package.xml`` declares; any other package cannot be accounted for and is refused.

Refusals carry the intake taxonomy code (:mod:`app.intake_error_taxonomy`):

* ``INPUT_ENCODING_INVALID`` — NULs, U+FFFD replacement characters or a byte-order mark (a UTF-16
  upload decoded as UTF-8);
* ``FORMAT_MISMATCH`` — not a single line reads as a ROS 2 field or constant;
* ``INPUT_MALFORMED`` — a line that is neither (a missing name, an unknown primitive, a default
  that does not parse as its type, a default on a message-typed field …), or too many sections;
* ``INPUT_TRUNCATED`` — a ``.srv`` or ``.action`` with fewer sections than its kind requires;
* ``INPUT_SEMANTIC_INVALID`` — an interface with no fields and no constants, a duplicated name,
  or a package with no interface files;
* ``INPUT_REFERENCE_UNRESOLVED`` — a reference the import cannot account for (see above).
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Dict, FrozenSet, List, Mapping, Optional, Sequence, Tuple, Union

from .fileset import IntakeFileset
from .secure_xml import SecureXmlError, parse_xml

__all__ = [
    "FORMAT_KEY",
    "INTERFACE_SUFFIXES",
    "PACKAGE_MANIFEST",
    "PRIMITIVE_TYPES",
    "SECTION_ROLES",
    "STANDARD_INTERFACE_PACKAGES",
    "Ros2Constant",
    "Ros2Document",
    "Ros2Field",
    "Ros2Interface",
    "Ros2Package",
    "Ros2ParseError",
    "Ros2Reference",
    "Ros2Section",
    "Ros2Type",
    "has_interface_lines",
    "interface_name_from_path",
    "is_package_manifest",
    "parse_ros2_fileset",
    "parse_ros2_text",
    "parse_type",
    "raw_record",
]

#: The adapter / normalizer format key.
FORMAT_KEY = "ros2"

#: Interface file suffix → interface kind.
_SUFFIX_KINDS: Dict[str, str] = {".msg": "msg", ".srv": "srv", ".action": "action"}

#: Every interface file suffix, most common first.
INTERFACE_SUFFIXES: Tuple[str, ...] = tuple(_SUFFIX_KINDS)

#: The package manifest's file name.
PACKAGE_MANIFEST = "package.xml"

#: Interface kind → the roles of its sections, in file order.
SECTION_ROLES: Dict[str, Tuple[str, ...]] = {
    "msg": ("message",),
    "srv": ("request", "response"),
    "action": ("goal", "result", "feedback"),
}

#: The ROS 2 primitive types (``rosidl`` built-in types).
PRIMITIVE_TYPES: FrozenSet[str] = frozenset(
    {
        "bool",
        "byte",
        "char",
        "float32",
        "float64",
        "int8",
        "uint8",
        "int16",
        "uint16",
        "int32",
        "uint32",
        "int64",
        "uint64",
        "string",
        "wstring",
    }
)

#: Integer primitive → inclusive (minimum, maximum).
_INTEGER_RANGES: Dict[str, Tuple[int, int]] = {
    "byte": (0, 255),
    "char": (0, 255),
    "int8": (-(2**7), 2**7 - 1),
    "uint8": (0, 2**8 - 1),
    "int16": (-(2**15), 2**15 - 1),
    "uint16": (0, 2**16 - 1),
    "int32": (-(2**31), 2**31 - 1),
    "uint32": (0, 2**32 - 1),
    "int64": (-(2**63), 2**63 - 1),
    "uint64": (0, 2**64 - 1),
}

_FLOAT_TYPES = frozenset({"float32", "float64"})
_STRING_TYPES = frozenset({"string", "wstring"})

#: The interface packages a ROS 2 distribution ships (``common_interfaces``, ``rcl_interfaces``
#: and the core ``builtin_interfaces`` / action packages). A reference into one of them from a file
#: imported on its own is expected, so it is kept as a declared external reference rather than
#: refused; the types themselves are not bundled, so the reference stays unresolved.
STANDARD_INTERFACE_PACKAGES: FrozenSet[str] = frozenset(
    {
        "action_msgs",
        "actionlib_msgs",
        "builtin_interfaces",
        "composition_interfaces",
        "diagnostic_msgs",
        "example_interfaces",
        "geometry_msgs",
        "lifecycle_msgs",
        "nav_msgs",
        "rcl_interfaces",
        "rosgraph_msgs",
        "sensor_msgs",
        "service_msgs",
        "shape_msgs",
        "statistics_msgs",
        "std_msgs",
        "std_srvs",
        "stereo_msgs",
        "tf2_msgs",
        "trajectory_msgs",
        "type_description_interfaces",
        "unique_identifier_msgs",
        "visualization_msgs",
    }
)

#: ``package.xml`` elements that declare a dependency on another package.
_DEPENDENCY_TAGS: Tuple[str, ...] = ("depend", "build_depend", "exec_depend", "build_export_depend")

#: ``package.xml`` markers of an interface package.
_INTERFACE_PACKAGE_MARKERS: Tuple[str, ...] = ("rosidl_interface_packages", "rosidl_default_generators")

_PACKAGE_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_TYPE_NAME_RE = re.compile(r"^[A-Z][A-Za-z0-9]*$")
_FIELD_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_CONSTANT_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
#: ``<base>[<=N]?[array]?`` — the base is a primitive, ``Name``, ``pkg/Name`` or ``pkg/msg/Name``.
_TYPE_RE = re.compile(
    r"^(?P<base>[A-Za-z][A-Za-z0-9_]*(?:/(?:msg/)?[A-Za-z][A-Za-z0-9_]*)?)"
    r"(?:<=(?P<string_bound>\d+))?"
    r"(?:\[(?P<array>(?:<=)?\d*)\])?$"
)
_CONSTANT_RE = re.compile(r"^(?P<name>[A-Za-z][A-Za-z0-9_]*)\s*=\s*(?P<value>.*)$")
_FIELD_RE = re.compile(r"^(?P<name>[A-Za-z][A-Za-z0-9_]*)(?:\s+(?P<default>.+))?$")
#: A comment that only draws a rule (``# ----- goal``) documents nothing.
_RULE_COMMENT_RE = re.compile(r"^(?:-{3,}|={3,}|\*{3,})")
_SEPARATOR = "---"
#: Characters that betray a non-UTF-8 upload decoded as UTF-8.
_ENCODING_FAULT_MARKERS = ("\x00", "�")


class Ros2ParseError(ValueError):
    """The input is not a readable ROS 2 interface (or package).

    Args:
        message: Human-readable description, naming the file and line where it can.
        code: The intake taxonomy code (see the module docstring).
    """

    def __init__(self, message: str, *, code: Optional[str] = None) -> None:
        super().__init__(message)
        self.code = code


# ===========================================================================
# The parsed model
# ===========================================================================


@dataclass(frozen=True)
class Ros2Type:
    """A field or constant type as written (``string<=8[<=4]``).

    Attributes:
        text: The type token exactly as written.
        base: The primitive name, or the referenced message's name (without its package).
        package: The package of a qualified reference (``geometry_msgs``), else ``None``.
        string_bound: The ``<=N`` upper bound of a bounded ``string`` / ``wstring``.
        array: ``None`` for a scalar, else ``unbounded``, ``fixed`` or ``bounded``.
        array_size: The size of a fixed array, or the upper bound of a bounded one.
    """

    text: str
    base: str
    package: Optional[str] = None
    string_bound: Optional[int] = None
    array: Optional[str] = None
    array_size: Optional[int] = None

    @property
    def is_primitive(self) -> bool:
        """Whether the element type is a ROS 2 primitive."""
        return self.package is None and self.base in PRIMITIVE_TYPES

    @property
    def is_array(self) -> bool:
        """Whether the type is an array of any kind."""
        return self.array is not None

    @property
    def reference(self) -> Optional[str]:
        """The referenced message as written without ``/msg/`` (``geometry_msgs/Pose``), or ``None``."""
        if self.is_primitive:
            return None
        return f"{self.package}/{self.base}" if self.package else self.base


@dataclass(frozen=True)
class Ros2Field:
    """One field line.

    Attributes:
        name: The field name.
        type: The field type.
        default: The default value, parsed to its Python value (a list for an array), else ``None``.
        default_text: The default exactly as written.
        description: The comment documenting the field.
        line: 1-based line number in its file.
    """

    name: str
    type: Ros2Type
    default: Any = None
    default_text: Optional[str] = None
    description: Optional[str] = None
    line: int = 0


@dataclass(frozen=True)
class Ros2Constant:
    """One constant line (``uint8 STATE_EMPTY=0``).

    Attributes:
        name: The constant name.
        type: The constant's primitive type (never an array).
        value: The value, parsed to its Python value.
        value_text: The value exactly as written.
        description: The comment documenting the constant.
        line: 1-based line number in its file.
    """

    name: str
    type: Ros2Type
    value: Any
    value_text: str
    description: Optional[str] = None
    line: int = 0


@dataclass(frozen=True)
class Ros2Section:
    """One ``---``-delimited section of an interface.

    Attributes:
        role: ``message``; ``request`` / ``response``; or ``goal`` / ``result`` / ``feedback``.
        fields: The section's fields, in file order.
        constants: The section's constants, in file order.
    """

    role: str
    fields: Tuple[Ros2Field, ...] = ()
    constants: Tuple[Ros2Constant, ...] = ()


@dataclass(frozen=True)
class Ros2Interface:
    """One interface file.

    Attributes:
        kind: ``msg``, ``srv`` or ``action``.
        name: The interface name (the file stem, ``NavigateToPose``).
        package: The package it belongs to, when a ``package.xml`` names it.
        path: The file's path in the import (or the upload's label).
        description: The comment block at the top of the file.
        sections: The sections, in the order :data:`SECTION_ROLES` gives for the kind.
    """

    kind: str
    name: str
    package: Optional[str]
    path: Optional[str]
    description: Optional[str]
    sections: Tuple[Ros2Section, ...]

    @property
    def full_name(self) -> str:
        """The ROS 2 interface name (``nav2_msgs/action/NavigateToPose``, or ``action/X`` with no package)."""
        local = f"{self.kind}/{self.name}"
        return f"{self.package}/{local}" if self.package else local

    def section(self, role: str) -> Optional[Ros2Section]:
        """The section with ``role``, or ``None``."""
        for section in self.sections:
            if section.role == role:
                return section
        return None


@dataclass(frozen=True)
class Ros2Package:
    """One ``package.xml``.

    Attributes:
        name: The package name.
        path: The manifest's path in the import.
        version: The declared package version.
        description: The declared description.
        license: The declared licence.
        dependencies: Every package named by a dependency element, sorted.
        interface_package: Whether the manifest declares itself an interface package.
    """

    name: str
    path: Optional[str]
    version: Optional[str] = None
    description: Optional[str] = None
    license: Optional[str] = None
    dependencies: Tuple[str, ...] = ()
    interface_package: bool = False


@dataclass(frozen=True)
class Ros2Reference:
    """How one message reference was resolved.

    Attributes:
        status: ``resolved`` (an interface in the import), ``external`` (another package, not in
            the import) or ``sibling`` (a bare name whose package's other files were not supplied).
        package: The package the referenced message belongs to, when known.
        name: The referenced message's name.
    """

    status: str
    package: Optional[str]
    name: str


@dataclass(frozen=True)
class Ros2Document:
    """A parsed ROS 2 input — one interface file, or a package fileset.

    Attributes:
        interfaces: Every interface read, in path order.
        packages: Every ``package.xml`` read, in path order.
        label: The upload's label (file name or root path).
        is_fileset: Whether the input was a fileset.
        sources: Interface path → its text, kept for the raw record.
    """

    interfaces: Tuple[Ros2Interface, ...]
    packages: Tuple[Ros2Package, ...] = ()
    label: Optional[str] = None
    is_fileset: bool = False
    sources: Mapping[str, str] = field(default_factory=dict)

    @property
    def package_names(self) -> FrozenSet[str]:
        """Every package that has at least one interface in the import."""
        return frozenset(i.package for i in self.interfaces if i.package)

    def message(self, package: Optional[str], name: str) -> Optional[Ros2Interface]:
        """The ``.msg`` interface ``name`` of ``package`` in the import, or ``None``."""
        for interface in self.interfaces:
            if interface.kind == "msg" and interface.package == package and interface.name == name:
                return interface
        return None

    def declared_dependencies(self, package: Optional[str]) -> FrozenSet[str]:
        """The dependencies ``package``'s manifest declares (every manifest's, for no package)."""
        found: List[str] = []
        for manifest in self.packages:
            if package is None or manifest.name == package:
                found.extend(manifest.dependencies)
        return frozenset(found)

    def resolve(self, type_: Ros2Type, owner: Ros2Interface) -> Optional[Ros2Reference]:
        """Resolve a field's message reference against the import.

        Args:
            type_: The field type.
            owner: The interface the field belongs to.

        Returns:
            ``None`` for a primitive, else how the reference resolves.

        Raises:
            Ros2ParseError: ``INPUT_REFERENCE_UNRESOLVED`` when the import cannot account for it.
        """
        if type_.is_primitive:
            return None
        where = _where(owner.path)
        if type_.package is None or type_.package == owner.package:
            if self.message(owner.package, type_.base) is not None:
                return Ros2Reference("resolved", owner.package, type_.base)
            if self.is_fileset:
                package = owner.package or "the uploaded package"
                raise Ros2ParseError(
                    f"`{type_.reference}`{where} names a message of {package}, but no "
                    f"`{type_.base}.msg` is in the import",
                    code="INPUT_REFERENCE_UNRESOLVED",
                )
            return Ros2Reference("sibling", owner.package, type_.base)
        package = type_.package
        if package in self.package_names:
            if self.message(package, type_.base) is not None:
                return Ros2Reference("resolved", package, type_.base)
            raise Ros2ParseError(
                f"`{type_.reference}`{where}: package {package} is in the import but defines no `{type_.base}` message",
                code="INPUT_REFERENCE_UNRESOLVED",
            )
        if package in STANDARD_INTERFACE_PACKAGES or package in self.declared_dependencies(owner.package):
            return Ros2Reference("external", package, type_.base)
        raise Ros2ParseError(
            f"`{type_.reference}`{where}: package {package} is not in the import, is not a standard "
            "ROS 2 interface package, and no package.xml declares a dependency on it",
            code="INPUT_REFERENCE_UNRESOLVED",
        )


# ===========================================================================
# Line grammar
# ===========================================================================


def _where(path: Optional[str], line: Optional[int] = None) -> str:
    """`` (file:line)`` for a message, or an empty string."""
    if path and line:
        return f" ({path}:{line})"
    if path:
        return f" ({path})"
    if line:
        return f" (line {line})"
    return ""


def parse_type(text: str) -> Ros2Type:
    """Parse a type token (``float64[<=10]``, ``geometry_msgs/msg/Pose``, ``string<=32``).

    Args:
        text: The type token.

    Returns:
        The parsed type.

    Raises:
        ValueError: When the token is not a valid ROS 2 type.
    """
    match = _TYPE_RE.match(text)
    if not match:
        raise ValueError(f"`{text}` is not a ROS 2 type")
    base = match.group("base")
    package: Optional[str] = None
    if "/" in base:
        package, _, base = base.partition("/")
        base = base.split("/")[-1]
        if not _PACKAGE_NAME_RE.match(package):
            raise ValueError(f"`{package}` is not a ROS 2 package name")
        if not _TYPE_NAME_RE.match(base):
            raise ValueError(f"`{base}` is not a ROS 2 message name")
    elif base not in PRIMITIVE_TYPES and not _TYPE_NAME_RE.match(base):
        raise ValueError(f"`{base}` is neither a ROS 2 primitive nor a message name")
    bound = match.group("string_bound")
    if bound is not None and (package is not None or base not in _STRING_TYPES):
        raise ValueError(f"`{text}`: only string and wstring take an upper bound")
    array_text = match.group("array")
    array: Optional[str] = None
    size: Optional[int] = None
    if array_text is not None:
        if array_text == "":
            array = "unbounded"
        elif array_text.startswith("<="):
            if array_text == "<=":
                raise ValueError(f"`{text}`: a bounded array needs its bound")
            array, size = "bounded", int(array_text[2:])
        else:
            array, size = "fixed", int(array_text)
        if size is not None and size <= 0:
            raise ValueError(f"`{text}`: an array bound must be positive")
    if bound is not None and int(bound) <= 0:
        raise ValueError(f"`{text}`: a string bound must be positive")
    return Ros2Type(
        text=text,
        base=base,
        package=package,
        string_bound=int(bound) if bound is not None else None,
        array=array,
        array_size=size,
    )


def _strip_comment(line: str) -> Tuple[str, Optional[str]]:
    """Split a line into its content and its ``#`` comment, ignoring ``#`` inside quotes."""
    quote: Optional[str] = None
    escaped = False
    for index, char in enumerate(line):
        if escaped:
            escaped = False
            continue
        if char == "\\" and quote:
            escaped = True
        elif quote:
            if char == quote:
                quote = None
        elif char in "\"'":
            quote = char
        elif char == "#":
            return line[:index].rstrip(), line[index + 1 :].strip()
    return line.rstrip(), None


def _comment_text(comment: str) -> Optional[str]:
    """A comment's documentation text, or ``None`` for an empty or rule-drawing comment."""
    text = comment.strip()
    if not text or _RULE_COMMENT_RE.match(text):
        return None
    return text


def _unquote(text: str) -> str:
    """The value of a quoted string literal (``"a \\"b\\""`` → ``a "b"``), or ``text`` unquoted."""
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        try:
            value = ast.literal_eval(text)
        except (ValueError, SyntaxError):
            return text[1:-1]
        return value if isinstance(value, str) else text[1:-1]
    return text


def _scalar_value(base: str, text: str) -> Any:
    """Parse one value of a primitive type.

    Raises:
        ValueError: When ``text`` is not a value of ``base``.
    """
    text = text.strip()
    if base in _STRING_TYPES:
        return _unquote(text)
    if base == "bool":
        lowered = text.lower()
        if lowered in ("true", "1"):
            return True
        if lowered in ("false", "0"):
            return False
        raise ValueError(f"`{text}` is not a bool")
    if base in _FLOAT_TYPES:
        try:
            return float(text)
        except ValueError as exc:
            raise ValueError(f"`{text}` is not a {base}") from exc
    try:
        value = int(text, 0)
    except ValueError as exc:
        raise ValueError(f"`{text}` is not a {base}") from exc
    low, high = _INTEGER_RANGES[base]
    if not low <= value <= high:
        raise ValueError(f"`{text}` is outside the {base} range")
    return value


def _split_array_literal(text: str) -> List[str]:
    """Split ``[a, "b,c", d]`` into its element texts, respecting quotes."""
    inner = text.strip()[1:-1]
    if not inner.strip():
        return []
    items: List[str] = []
    current: List[str] = []
    quote: Optional[str] = None
    for char in inner:
        if quote:
            current.append(char)
            if char == quote:
                quote = None
        elif char in "\"'":
            quote = char
            current.append(char)
        elif char == ",":
            items.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    items.append("".join(current).strip())
    return items


def _default_value(type_: Ros2Type, text: str) -> Any:
    """Parse a field default against its type.

    Raises:
        ValueError: When the type takes no default or ``text`` does not parse as one.
    """
    if not type_.is_primitive:
        raise ValueError(f"a {type_.text} field takes no default value")
    if not type_.is_array:
        value = _scalar_value(type_.base, text)
        _check_string_bound(type_, value)
        return value
    stripped = text.strip()
    if not (stripped.startswith("[") and stripped.endswith("]")):
        raise ValueError(f"the default of an array field is a `[...]` list, not `{text}`")
    values = [_scalar_value(type_.base, item) for item in _split_array_literal(stripped)]
    for value in values:
        _check_string_bound(type_, value)
    if type_.array == "fixed" and len(values) != type_.array_size:
        raise ValueError(f"a {type_.text} default needs exactly {type_.array_size} values")
    if type_.array == "bounded" and type_.array_size is not None and len(values) > type_.array_size:
        raise ValueError(f"a {type_.text} default holds at most {type_.array_size} values")
    return values


def _check_string_bound(type_: Ros2Type, value: Any) -> None:
    """Refuse a string value longer than its type's bound."""
    if type_.string_bound is not None and isinstance(value, str) and len(value) > type_.string_bound:
        raise ValueError(f"`{value}` is longer than {type_.text} allows")


def _read_line(content: str) -> Tuple[str, Any]:
    """Read one content line as a field or a constant.

    Returns:
        ``("field", (name, type, default, default_text))`` or
        ``("constant", (name, type, value, value_text))``.

    Raises:
        ValueError: When the line is neither, saying why.
    """
    parts = content.split(None, 1)
    if len(parts) < 2:
        raise ValueError(f"`{content.strip()}` has a type but no name")
    type_text, rest = parts[0], parts[1].strip()
    type_ = parse_type(type_text)
    constant = _CONSTANT_RE.match(rest)
    if constant:
        name = constant.group("name")
        if not _CONSTANT_NAME_RE.match(name):
            raise ValueError(f"constant `{name}` must be UPPER_CASE")
        if not type_.is_primitive or type_.is_array:
            raise ValueError(f"constant `{name}` must have a primitive, non-array type")
        value_text = constant.group("value").strip()
        if not value_text:
            raise ValueError(f"constant `{name}` has no value")
        value = _scalar_value(type_.base, value_text)
        _check_string_bound(type_, value)
        return "constant", (name, type_, value, value_text)
    match = _FIELD_RE.match(rest)
    if not match:
        raise ValueError(f"`{rest}` is not a field name")
    name = match.group("name")
    if not _FIELD_NAME_RE.match(name) or "__" in name or name.endswith("_"):
        raise ValueError(f"field `{name}` must be lower_snake_case")
    default_text = match.group("default")
    default = _default_value(type_, default_text) if default_text is not None else None
    return "field", (name, type_, default, default_text.strip() if default_text else None)


# ===========================================================================
# Files
# ===========================================================================


def interface_name_from_path(path: Optional[str]) -> Optional[str]:
    """The interface name a file path gives (``msg/LoadCell.msg`` → ``LoadCell``).

    A stem that is not already a ROS 2 type name is camel-cased word by word, dropping leading
    numeric words (``05-real-world-navigate-to-pose`` → ``RealWorldNavigateToPose``).
    """
    if not path:
        return None
    stem = PurePosixPath(path).stem
    if _TYPE_NAME_RE.match(stem):
        return stem
    words = [word for word in re.split(r"[^A-Za-z0-9]+", stem) if word]
    while words and words[0].isdigit():
        words.pop(0)
    name = "".join(word[0].upper() + word[1:] for word in words)
    if not name:
        return None
    return name if name[0].isalpha() else f"T{name}"


def _kind_from_path(path: Optional[str]) -> Optional[str]:
    """The interface kind a file suffix declares, or ``None``."""
    if not path:
        return None
    return _SUFFIX_KINDS.get(PurePosixPath(path).suffix.lower())


def _check_encoding(text: str, path: Optional[str]) -> None:
    """Refuse text that was decoded from a non-UTF-8 upload."""
    if text.startswith("﻿") or any(marker in text for marker in _ENCODING_FAULT_MARKERS):
        raise Ros2ParseError(
            f"The interface{_where(path)} is not UTF-8 text (NULs, replacement characters or a "
            "byte-order mark); ROS 2 interface files are UTF-8",
            code="INPUT_ENCODING_INVALID",
        )


@dataclass
class _SectionDraft:
    """A section being read."""

    fields: List[Ros2Field] = field(default_factory=list)
    constants: List[Ros2Constant] = field(default_factory=list)


def _read_interface(text: str, *, path: Optional[str], package: Optional[str], name: Optional[str]) -> Ros2Interface:
    """Read one interface file.

    Args:
        text: The file text.
        path: Its path or label (the suffix gives the kind).
        package: The package it belongs to, when known.
        name: Its interface name; derived from ``path`` when ``None``.

    Returns:
        The interface.

    Raises:
        Ros2ParseError: See the module docstring.
    """
    _check_encoding(text, path)
    drafts: List[_SectionDraft] = [_SectionDraft()]
    header: List[str] = []
    in_header = True
    pending: List[str] = []
    errors: List[str] = []
    readable = 0
    for number, raw_line in enumerate(text.splitlines(), start=1):
        content, comment = _strip_comment(raw_line)
        stripped = content.strip()
        if stripped == _SEPARATOR:
            drafts.append(_SectionDraft())
            in_header = False
            pending = []
            continue
        if not stripped:
            if comment is not None:
                doc = _comment_text(comment)
                if doc is None:
                    continue
                (header if in_header else pending).append(doc)
            else:
                in_header = False
                pending = []
            continue
        in_header = False
        try:
            line_kind, parsed = _read_line(stripped)
        except ValueError as exc:
            errors.append(f"line {number}: {exc}")
            pending = []
            continue
        readable += 1
        trailing = _comment_text(comment) if comment is not None else None
        description = " ".join(pending + ([trailing] if trailing else [])) or None
        pending = []
        if line_kind == "constant":
            const_name, type_, value, value_text = parsed
            drafts[-1].constants.append(
                Ros2Constant(const_name, type_, value, value_text, description=description, line=number)
            )
        else:
            field_name, type_, default, default_text = parsed
            drafts[-1].fields.append(
                Ros2Field(field_name, type_, default, default_text, description=description, line=number)
            )
    where = _where(path)
    if errors and readable == 0:
        raise Ros2ParseError(
            f"Not a ROS 2 interface{where}: no line reads as a field or a constant ({errors[0]})",
            code="FORMAT_MISMATCH",
        )
    if errors:
        shown = "; ".join(errors[:5])
        more = f" (and {len(errors) - 5} more)" if len(errors) > 5 else ""
        raise Ros2ParseError(f"Malformed ROS 2 interface{where}: {shown}{more}", code="INPUT_MALFORMED")

    kind: Optional[str] = _kind_from_path(path) or {1: "msg", 2: "srv", 3: "action"}.get(len(drafts))
    if kind is None:
        raise Ros2ParseError(
            f"A ROS 2 interface{where} has at most three `---`-separated sections; this one has {len(drafts)}",
            code="INPUT_MALFORMED",
        )
    roles = SECTION_ROLES[kind]
    if len(drafts) < len(roles):
        missing = ", ".join(roles[len(drafts) :])
        raise Ros2ParseError(
            f"The .{kind} file{where} ends after {len(drafts)} of its {len(roles)} sections; "
            f"missing: {missing}. The file looks cut short",
            code="INPUT_TRUNCATED",
        )
    if len(drafts) > len(roles):
        raise Ros2ParseError(
            f"A .{kind} file{where} has {len(roles)} section(s) but this one has {len(drafts)}",
            code="INPUT_MALFORMED",
        )
    if not any(d.fields or d.constants for d in drafts):
        raise Ros2ParseError(
            f"The ROS 2 interface{where} declares no fields and no constants, so there is no schema to import",
            code="INPUT_SEMANTIC_INVALID",
        )
    sections: List[Ros2Section] = []
    for role, draft in zip(roles, drafts):
        seen: Dict[str, int] = {}
        members: List[Union[Ros2Field, Ros2Constant]] = [*draft.fields, *draft.constants]
        for member in members:
            if member.name in seen:
                raise Ros2ParseError(
                    f"`{member.name}` is declared twice in the {role} section{_where(path, member.line)}",
                    code="INPUT_SEMANTIC_INVALID",
                )
            seen[member.name] = member.line
        sections.append(Ros2Section(role, tuple(draft.fields), tuple(draft.constants)))
    resolved_name = (
        name or interface_name_from_path(path) or {"msg": "Message", "srv": "Service", "action": "Action"}[kind]
    )
    return Ros2Interface(
        kind=kind,
        name=resolved_name,
        package=package,
        path=path,
        description=" ".join(header) or None,
        sections=tuple(sections),
    )


def is_package_manifest(text: Optional[str]) -> bool:
    """Whether ``text`` looks like an interface package's ``package.xml``."""
    if not text or "<package" not in text:
        return False
    return any(marker in text for marker in _INTERFACE_PACKAGE_MARKERS)


def _element_text(root: Any, tag: str) -> Optional[str]:
    """The stripped text of ``root``'s first ``tag`` child, or ``None``."""
    element = root.find(tag)
    if element is None or element.text is None:
        return None
    return " ".join(element.text.split()) or None


def _read_package(text: str, *, path: Optional[str]) -> Ros2Package:
    """Read a ``package.xml``.

    Raises:
        Ros2ParseError: When the manifest is not well-formed or names no valid package.
    """
    try:
        root = parse_xml(text, source_label=path)
    except SecureXmlError as exc:
        raise Ros2ParseError(
            f"Unreadable package.xml{_where(path)}: {exc}", code=getattr(exc, "code", None) or "INPUT_MALFORMED"
        ) from exc
    if root.tag != "package":
        raise Ros2ParseError(f"package.xml{_where(path)} has no <package> root", code="INPUT_MALFORMED")
    name = _element_text(root, "name")
    if not name or not _PACKAGE_NAME_RE.match(name):
        raise Ros2ParseError(
            f"package.xml{_where(path)} names no valid package (`{name}`)", code="INPUT_SEMANTIC_INVALID"
        )
    dependencies = sorted(
        {
            " ".join(element.text.split())
            for tag in _DEPENDENCY_TAGS
            for element in root.findall(tag)
            if element.text and element.text.strip()
        }
    )
    groups = [" ".join((element.text or "").split()) for element in root.findall("member_of_group")]
    build_tools = [" ".join((element.text or "").split()) for element in root.findall("buildtool_depend")]
    return Ros2Package(
        name=name,
        path=path,
        version=_element_text(root, "version"),
        description=_element_text(root, "description"),
        license=_element_text(root, "license"),
        dependencies=tuple(dependencies),
        interface_package=any(marker in groups + build_tools for marker in _INTERFACE_PACKAGE_MARKERS),
    )


def has_interface_lines(text: Optional[str]) -> Tuple[int, int]:
    """Count the lines of ``text`` that do and do not read as ROS 2 fields or constants.

    Used by detection: comments, blank lines and ``---`` separators count as neither.

    Returns:
        ``(readable, unreadable)``.
    """
    if not text:
        return 0, 0
    readable = unreadable = 0
    for raw_line in text.splitlines():
        content, _ = _strip_comment(raw_line)
        stripped = content.strip()
        if not stripped or stripped == _SEPARATOR:
            continue
        try:
            _read_line(stripped)
        except ValueError:
            unreadable += 1
        else:
            readable += 1
    return readable, unreadable


def _check_references(document: Ros2Document) -> None:
    """Resolve every message reference once, so an unresolvable one is refused at parse time."""
    for interface in document.interfaces:
        for section in interface.sections:
            for member in section.fields:
                document.resolve(member.type, interface)


def parse_ros2_text(text: str, *, label: Optional[str] = None) -> Ros2Document:
    """Parse one uploaded interface file (or a lone ``package.xml``).

    Args:
        text: The file text.
        label: The upload's file name or path; its suffix names the interface kind.

    Returns:
        The parsed document.

    Raises:
        Ros2ParseError: See the module docstring.
    """
    if text is None or not text.strip():
        raise Ros2ParseError("The ROS 2 interface is empty", code="INPUT_EMPTY")
    if (label and PurePosixPath(label).name == PACKAGE_MANIFEST) or (
        _kind_from_path(label) is None and is_package_manifest(text)
    ):
        package = _read_package(text, path=label)
        raise Ros2ParseError(
            f"package.xml for {package.name} lists no interface files; import the package as an "
            "archive with its msg/, srv/ and action/ files",
            code="INPUT_SEMANTIC_INVALID",
        )
    interface = _read_interface(text, path=label, package=None, name=None)
    document = Ros2Document(
        interfaces=(interface,), label=label, is_fileset=False, sources={label or interface.name: text}
    )
    _check_references(document)
    return document


def _owning_package(path: str, manifests: Sequence[Tuple[PurePosixPath, Ros2Package]]) -> Optional[str]:
    """The package whose ``package.xml`` is the nearest ancestor of ``path``."""
    member = PurePosixPath(path)
    best: Optional[Tuple[int, str]] = None
    for directory, package in manifests:
        if directory == PurePosixPath(".") or directory in member.parents:
            depth = len(directory.parts)
            if best is None or depth > best[0]:
                best = (depth, package.name)
    return best[1] if best else None


def parse_ros2_fileset(fileset: IntakeFileset, *, label: Optional[str] = None) -> Ros2Document:
    """Parse an interface package (or several) uploaded as a fileset.

    Every ``package.xml`` and every ``.msg`` / ``.srv`` / ``.action`` member is read; any other
    member (``CMakeLists.txt``, a README) is ignored. An interface belongs to the package whose
    manifest is its nearest ancestor.

    Args:
        fileset: The uploaded set.
        label: The upload's label.

    Returns:
        The parsed document, interfaces in path order.

    Raises:
        Ros2ParseError: See the module docstring.
    """
    manifests: List[Tuple[PurePosixPath, Ros2Package]] = []
    for path in sorted(fileset.members):
        if PurePosixPath(path).name == PACKAGE_MANIFEST:
            text = fileset.members[path]
            _check_encoding(text, path)
            manifests.append((PurePosixPath(path).parent, _read_package(text, path=path)))
    interfaces: List[Ros2Interface] = []
    sources: Dict[str, str] = {}
    for path in sorted(fileset.members):
        if _kind_from_path(path) is None:
            continue
        text = fileset.members[path]
        if not text.strip():
            raise Ros2ParseError(f"The interface file {path} is empty", code="INPUT_EMPTY")
        interfaces.append(_read_interface(text, path=path, package=_owning_package(path, manifests), name=None))
        sources[path] = text
    if not interfaces:
        raise Ros2ParseError(
            "The upload holds no .msg, .srv or .action files, so there is no interface to import",
            code="INPUT_SEMANTIC_INVALID",
        )
    seen: Dict[Tuple[Optional[str], str, str], str] = {}
    for interface in interfaces:
        identity = (interface.package, interface.kind, interface.name)
        if identity in seen:
            raise Ros2ParseError(
                f"{interface.full_name} is defined twice ({seen[identity]} and {interface.path})",
                code="INPUT_SEMANTIC_INVALID",
            )
        seen[identity] = interface.path or interface.name
    document = Ros2Document(
        interfaces=tuple(interfaces),
        packages=tuple(package for _, package in manifests),
        label=label or fileset.root,
        is_fileset=True,
        sources=sources,
    )
    _check_references(document)
    return document


def raw_record(document: Ros2Document) -> Dict[str, Any]:
    """The lossless native record kept on ``CanonicalApi.raw``: every file's text and every manifest."""
    return {
        "files": [{"path": path, "text": text} for path, text in sorted(document.sources.items())],
        "packages": [
            {
                "name": package.name,
                "path": package.path,
                "version": package.version,
                "dependencies": list(package.dependencies),
            }
            for package in document.packages
        ],
    }
