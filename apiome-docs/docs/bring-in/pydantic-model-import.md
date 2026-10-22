---
title: "Import Pydantic models"
description: "Catalog the Pydantic models in a Python module, read without running it."
sidebar_position: 8.8
tags: [import, pydantic, python, schema]
---

Pydantic models are where many Python services — FastAPI apps especially — describe their data,
with validation rules attached. Apiome imports a module's Pydantic models as **schema types** in the
catalog, with those rules as constraints.

## Your code is never run

Apiome reads the Python source **as text**: it parses it and works out the models from what is
written. It never imports or runs your module, so nothing at the top of the file — database calls,
environment lookups, side effects — happens during an import. The trade-off is that anything only
running the code could reveal is listed as a limit instead (see
[What is declared, not imported](#what-is-declared-not-imported)).

## What you can import

| You have | Import it as |
| --- | --- |
| One module that defines `BaseModel` subclasses | One file, or paste the source |
| A package whose modules import models from one another | One archive with all the modules; the root is the module whose models you want (for example `models.py`) |

The root module's own models, and the models it imports from the other modules in the upload, are
the catalog item. A model elsewhere in the package appears only when one of those refers to it.

## Import it

Import the file like any other specification: in the [import wizard](./import-wizard.mdx), with
`apiome import`, or through the REST API (see [Import a specification](./import-a-spec.md)). Apiome
recognises a module that imports `pydantic` and defines a `BaseModel` subclass, and picks
**Pydantic models** (`pydantic`).

The models land in the [Catalog](./catalog.mdx) as a schemas-only item, named after the root
module's first model.

## What each part becomes

| Pydantic | Becomes |
| --- | --- |
| `class Order(BaseModel)` | A record. Fields from base classes are included, in pydantic's order. |
| `class OrderPage(Page[Order])` (a generic model with a concrete type) | A record with `Order` in place of the type parameter |
| `class Status(str, Enum)`, `Literal["a", "b"]` | An enum |
| `Union[A, B]`, `A \| B` | A union; models are referenced by name |
| `Optional[X]`, `X \| None`, or a field with a default | A nullable field |
| A nested or self-referencing model | A reference to that model's record |
| `list[X]`, `set[X]`, `tuple[...]`, `dict[K, V]` | A list (a set adds unique items) or a map |
| `datetime`, `date`, `UUID`, `EmailStr`, `AnyUrl`, … | A string with the matching format |

Field rules are kept as constraints:

| Pydantic | Constraint |
| --- | --- |
| `Field(gt=…, ge=…, lt=…, le=…, multiple_of=…)` | Numeric bounds |
| `Field(min_length=…, max_length=…)` | Length on a string, item count on a list or set |
| `Field(pattern=…)` | A pattern |
| `Annotated[str, StringConstraints(…)]`, `Annotated[float, Field(…)]` | The same rules, wherever the alias is used |
| `Field(default=…)` or `= value` | The field's default (literal values and enum members) |
| `Field(description=…)`, `Field(deprecated=True)` | The description and deprecation |
| `Field(alias="orderId")`, `ConfigDict(alias_generator=to_camel)` | The field's name as it appears in JSON; the Python name is kept alongside |
| `ConfigDict(extra="forbid")` | Recorded on the record |

## What is declared, not imported

Apiome lists these in the import's coverage ledger instead of guessing:

- **Models built at runtime** — `create_model(...)`, or a function that returns one. Their fields
  only exist once the code runs, so they are left out.
- **Validators** (`field_validator`, `model_validator`) and **class hooks** (`__init_subclass__`, a
  custom metaclass). The model is imported; what the code checks or changes is not.
- **Computed fields** (`@computed_field`). They are not imported as fields.
- **Types Apiome cannot work out from the text**, or does not know. The field is left out rather
  than shown as "any".
- **Decimal precision** (`max_digits`, `decimal_places`) — kept on the field, but not as a
  constraint.

## When an import is refused

| Error code | Why |
| --- | --- |
| `INPUT_MALFORMED` | The module has a Python syntax error, such as bad indentation. |
| `INPUT_TRUNCATED` | The module ends in the middle of a class or call. |
| `INPUT_SEMANTIC_INVALID` | The module defines no `BaseModel` subclass. |
| `INPUT_REFERENCE_UNRESOLVED` | A field's type comes from a module that is not in the upload (and is not the standard library or pydantic). Add that module, or upload the package as an archive. |
| `FORMAT_MISMATCH` | The module does not import pydantic — standard dataclasses, for example. |
| `INPUT_ENCODING_INVALID` | The file is not UTF-8 (for example, it was saved as UTF-16). |

## Related

- [Import Zod schemas](./zod-schema-import.md) and [Import TypeScript types](./typescript-types-import.md):
  the same shapes from TypeScript, modelled the same way.
- [Supported formats](./supported-formats.md#format-pydantic): what this importer reads.
- [Read a catalog item's format details](./catalog-format-details.md): where the coverage ledger
  lists what was declared.
