"""Avro Parsing Canonical Form and semantic hashes — MFI-12.1 (#3782).

Avro defines its own schema identity: the **Parsing Canonical Form** (PCF) of the
`Avro 1.12 specification <https://avro.apache.org/docs/1.12.0/specification/#parsing-canonical-form-for-schemas>`_,
hashed with the 64-bit **CRC-64-AVRO** (Rabin) fingerprint or SHA-256. PCF keeps only what a
reader needs to decode the binary encoding — names, types, fields in order, symbols, items,
values, sizes — and strips everything else, including ``doc``, ``default``, ``aliases``,
``order`` and ``logicalType``. Two schemas with the same PCF read and write the same bytes.

That is the wrong question for "did this schema change?". ``default``, ``aliases`` and
``order`` are load-bearing for schema *evolution* (a reader's default fills a field the writer
dropped; an alias renames a field without breaking old data), so this module also computes a
**semantic hash**: the same normalization (full names, named types inlined once, no
whitespace) with every attribute kept and keys sorted. A ``doc``-only edit therefore flips the
semantic hash but never the PCF.

Both are computed for every named type a document declares, each with its referenced named
types inlined at first use, as PCF requires. A ``.avsc`` (or schema-only IDL) document's own
fingerprint is its root type's; an IDL *protocol* has no single schema, so it has per-type
fingerprints only.

The module is pure: no I/O, the same document always gives the same hashes.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Set, Tuple

from .avro_parser import AvroDocument
from .canonical_model import CanonicalApi
from .fingerprint import FingerprintHasher

__all__ = [
    "PCF_ALGORITHM",
    "AvroSchemaFingerprint",
    "crc64_avro",
    "parsing_canonical_form",
    "semantic_form",
    "fingerprint_types",
    "document_fingerprint",
    "AvroPcfHasher",
]

#: Algorithm label of the document-level PCF hash (``FingerprintResult.format_algorithm``).
PCF_ALGORITHM = "avro-parsing-canonical-form-sha256"

_PRIMITIVES = frozenset({"null", "boolean", "int", "long", "float", "double", "bytes", "string"})
_NAMED = frozenset({"record", "error", "enum", "fixed"})

#: PCF [STRIP] keeps only these attributes, in this [ORDER].
_PCF_KEYS = ("name", "type", "fields", "symbols", "items", "values", "size")

#: CRC-64-AVRO empty value and polynomial table (Avro specification, "Schema Fingerprints").
_CRC64_EMPTY = 0xC15D213AA4D7A795


def _crc64_table() -> Tuple[int, ...]:
    table = []
    for i in range(256):
        fp = i
        for _ in range(8):
            fp = (fp >> 1) ^ (_CRC64_EMPTY & -(fp & 1))
        table.append(fp)
    return tuple(table)


_CRC64_TABLE = _crc64_table()


def crc64_avro(data: bytes) -> int:
    """Return the 64-bit CRC-64-AVRO (Rabin) fingerprint of ``data``.

    Args:
        data: The bytes to fingerprint — for a schema, its PCF encoded as UTF-8.

    Returns:
        The fingerprint as an unsigned 64-bit integer. Java's
        ``SchemaNormalization.parsingFingerprint64`` returns the same value as a signed long;
        the single-object encoding header carries it little-endian.
    """
    fp = _CRC64_EMPTY
    for byte in data:
        fp = (fp >> 8) ^ _CRC64_TABLE[(fp ^ byte) & 0xFF]
    return fp


@dataclass(frozen=True)
class AvroSchemaFingerprint:
    """The fingerprints of one Avro schema.

    Attributes:
        name: The schema's full name.
        canonical_form: Its Parsing Canonical Form.
        crc64: CRC-64-AVRO of the PCF, as 16 lowercase hex digits of the 64-bit value.
        sha256: SHA-256 of the PCF, lowercase hex.
        semantic_sha256: SHA-256 of the semantic form (PCF normalization with ``doc``,
            ``default``, ``aliases``, ``order``, ``logicalType`` and custom attributes kept).
    """

    name: str
    canonical_form: str
    crc64: str
    sha256: str
    semantic_sha256: str

    def pcf_dict(self) -> Dict[str, str]:
        """Return the PCF hashes as recorded on the catalog item (``{"crc64", "sha256"}``)."""
        return {"crc64": self.crc64, "sha256": self.sha256}


def _full_name(name: str, namespace: Optional[str]) -> str:
    """Resolve ``name`` against ``namespace`` (a dotted name is already full)."""
    if "." in name or not namespace:
        return name
    return f"{namespace}.{name}"


def _namespace_of(full_name: str) -> Optional[str]:
    return full_name.rsplit(".", 1)[0] if "." in full_name else None


class _Canonicalizer:
    """One walk of a schema into PCF (``keep_all=False``) or the semantic form (``True``).

    Named types are inlined at their first occurrence and written by full name after that,
    as PCF requires; a reference to a type the walk has not met yet is inlined from the
    document's named-type store, so an IDL type that names a sibling is fingerprinted as the
    complete schema it stands for.
    """

    def __init__(self, store: Mapping[str, Dict[str, Any]], *, keep_all: bool) -> None:
        self._store = store
        self._keep_all = keep_all
        self._seen: Set[str] = set()

    def walk(self, schema: Any, namespace: Optional[str]) -> Any:
        """Return the canonical form of ``schema`` as a JSON-ready value."""
        if isinstance(schema, list):
            return [self.walk(branch, namespace) for branch in schema]
        if isinstance(schema, str):
            return self._reference(schema, namespace)
        if not isinstance(schema, dict):
            return schema
        schema_type = schema.get("type")
        if isinstance(schema_type, (dict, list)):
            # ``{"type": {...}}`` wraps a schema; PCF reduces it to the inner one.
            return self.walk(schema_type, namespace)
        if schema_type in _PRIMITIVES:
            extra = {k: v for k, v in schema.items() if k != "type"}
            if not self._keep_all or not extra:
                return schema_type  # [PRIMITIVES]
            return {"type": schema_type, **extra}
        if schema_type in _NAMED:
            return self._named(schema, namespace)
        if isinstance(schema_type, str) and schema_type not in ("array", "map"):
            # A named reference carrying attributes (``{"type": "Digest", "logicalType": …}``).
            reference = self._reference(schema_type, namespace)
            extra = {k: v for k, v in schema.items() if k != "type"}
            if not self._keep_all or not extra:
                return reference
            return {"type": reference, **extra}
        out: Dict[str, Any] = {}
        for key, value in schema.items():
            if key == "items" or key == "values":
                out[key] = self.walk(value, namespace)
            elif self._keep_all or key in _PCF_KEYS:
                out[key] = value
        return self._ordered(out)

    def _reference(self, name: str, namespace: Optional[str]) -> Any:
        if name in _PRIMITIVES:
            return name
        full = _full_name(name, namespace)
        if full not in self._seen and full in self._store:
            return self._named(self._store[full], _namespace_of(full))
        return full

    def _named(self, schema: Dict[str, Any], namespace: Optional[str]) -> Any:
        raw_name = schema.get("name")
        own_namespace = schema.get("namespace") if isinstance(schema.get("namespace"), str) else None
        full = _full_name(raw_name, own_namespace or namespace) if isinstance(raw_name, str) else None
        if full is not None:
            if full in self._seen:
                return full
            self._seen.add(full)
        inner_namespace = _namespace_of(full) if full else namespace
        out: Dict[str, Any] = {}
        for key, value in schema.items():
            if key == "namespace":
                continue  # [FULLNAMES]: the namespace is folded into the name
            if key == "name":
                out[key] = full
            elif key == "fields" and isinstance(value, list):
                out[key] = [self._field(field, inner_namespace) for field in value]
            elif self._keep_all or key in _PCF_KEYS:
                out[key] = value
        return self._ordered(out)

    def _field(self, field: Any, namespace: Optional[str]) -> Any:
        if not isinstance(field, dict):
            return field
        out: Dict[str, Any] = {}
        for key, value in field.items():
            if key == "type":
                out[key] = self.walk(value, namespace)
            elif self._keep_all or key == "name":
                out[key] = value
        return self._ordered(out)

    def _ordered(self, out: Dict[str, Any]) -> Dict[str, Any]:
        """PCF [ORDER] for the PCF keys; the semantic form sorts keys at serialization."""
        if self._keep_all:
            return out
        return {key: out[key] for key in _PCF_KEYS if key in out}


def _store_of(document: AvroDocument) -> Dict[str, Dict[str, Any]]:
    return {_full_name(named.name, named.namespace): named.schema for named in document.types}


def parsing_canonical_form(
    schema: Any,
    *,
    namespace: Optional[str] = None,
    store: Optional[Mapping[str, Dict[str, Any]]] = None,
) -> str:
    """Return the Parsing Canonical Form of an Avro schema.

    Args:
        schema: A parsed Avro schema (JSON value).
        namespace: The enclosing namespace a relative name resolves against.
        store: Named types (full name → schema) to inline when the schema references them.

    Returns:
        The PCF text: [PRIMITIVES], [FULLNAMES], [STRIP], [ORDER], [STRINGS], [INTEGERS] and
        [WHITESPACE] applied.
    """
    value = _Canonicalizer(store or {}, keep_all=False).walk(schema, namespace)
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def semantic_form(
    schema: Any,
    *,
    namespace: Optional[str] = None,
    store: Optional[Mapping[str, Dict[str, Any]]] = None,
) -> str:
    """Return the semantic form of an Avro schema: PCF normalization with every attribute kept.

    Full names replace namespaces and named types are inlined once, as in PCF, but ``doc``,
    ``default``, ``aliases``, ``order``, ``logicalType`` and custom attributes stay, object keys
    are sorted, and field and symbol order is preserved (it is meaningful).

    Args:
        schema: A parsed Avro schema (JSON value).
        namespace: The enclosing namespace a relative name resolves against.
        store: Named types (full name → schema) to inline when the schema references them.

    Returns:
        Compact JSON text.
    """
    value = _Canonicalizer(store or {}, keep_all=True).walk(schema, namespace)
    return json.dumps(value, separators=(",", ":"), sort_keys=True, ensure_ascii=False)


def _fingerprint(full_name: str, schema: Dict[str, Any], store: Mapping[str, Dict[str, Any]]) -> AvroSchemaFingerprint:
    namespace = _namespace_of(full_name)
    pcf = parsing_canonical_form(schema, namespace=namespace, store=store)
    semantic = semantic_form(schema, namespace=namespace, store=store)
    return AvroSchemaFingerprint(
        name=full_name,
        canonical_form=pcf,
        crc64=f"{crc64_avro(pcf.encode('utf-8')):016x}",
        sha256=hashlib.sha256(pcf.encode("utf-8")).hexdigest(),
        semantic_sha256=hashlib.sha256(semantic.encode("utf-8")).hexdigest(),
    )


def fingerprint_types(document: AvroDocument) -> Tuple[AvroSchemaFingerprint, ...]:
    """Fingerprint every named type ``document`` declares, sorted by full name.

    Args:
        document: A parsed ``.avsc`` or IDL document.

    Returns:
        One :class:`AvroSchemaFingerprint` per named type, each over the type with the named
        types it references inlined.
    """
    store = _store_of(document)
    return tuple(_fingerprint(full, store[full], store) for full in sorted(store))


def document_fingerprint(document: AvroDocument) -> Optional[AvroSchemaFingerprint]:
    """Return the document's own fingerprint: its root schema's, or ``None`` for a protocol.

    Args:
        document: A parsed ``.avsc`` or IDL document.

    Returns:
        The root type's fingerprint for a ``.avsc`` or schema-only IDL document; ``None`` for
        an IDL protocol, which is a set of types and messages rather than one schema.
    """
    if document.protocol is not None:
        return None
    root = document.root
    full = _full_name(root.name, root.namespace)
    return _fingerprint(full, root.schema, _store_of(document))


class AvroPcfHasher(FingerprintHasher, register=True):
    """Expose an Avro schema's PCF SHA-256 as ``FingerprintResult.format_hash``.

    Reads what the normalizer recorded (``extras["avro_pcf"]`` under ``extras["avro_root"]``),
    so it needs no re-parse. An IDL protocol, or a model built without those extras, has no
    document-level PCF and yields ``None``.
    """

    format = "avro"
    algorithm = PCF_ALGORITHM

    def hash(self, api: CanonicalApi) -> Optional[str]:
        """Return the root schema's PCF SHA-256, or ``None`` for a protocol.

        Args:
            api: An Avro canonical model.

        Returns:
            64 lowercase hex digits, or ``None``.
        """
        extras = api.extras or {}
        if extras.get("avro_protocol"):
            return None
        pcf = extras.get("avro_pcf")
        root = extras.get("avro_root")
        if not isinstance(pcf, dict) or not isinstance(pcf.get(root), dict):
            return None
        return pcf[root].get("sha256")
