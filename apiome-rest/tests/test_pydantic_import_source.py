"""Pydantic model import — FMT-8.4 (#5465).

Every test here runs in-process with no toolchain: the reader is pure static analysis.

* **No user module is executed** — the first acceptance criterion, proven by uploads whose
  top-level code would leave evidence (a file, an import of a planted module) if it ever ran;
* **constraints and annotations** — ``Field`` / ``Annotated`` constraints, ``Optional`` / unions /
  nested and self-referencing models, enums, generics, aliases and defaults;
* **declared limits** — dynamic construction, validators, computed fields, class hooks, unknown
  and unresolvable annotations;
* **intake** — detection and the taxonomy code of every rejection.
"""

from __future__ import annotations

import builtins
import sys
from typing import Dict

import pytest

from app.canonical_model import CanonicalApi, TypeKind
from app.fileset import IntakeFileset
from app.format_capability_registry import capability_for
from app.import_source import (
    DetectionInput,
    ImportSourceError,
    get_import_source,
    load_builtin_import_sources,
)
from app.pydantic_import_source import PYDANTIC_CAPABILITIES
from app.pydantic_normalizer import PYDANTIC_EXTRAS_KEY
from app.pydantic_parser import LIMIT_DETAILS, PARTIAL_LIMITS, is_pydantic_module

load_builtin_import_sources()

HEADER = "from typing import Annotated, Literal, Optional, Union\nfrom pydantic import BaseModel, Field\n"


@pytest.fixture()
def adapter():
    return get_import_source("pydantic")


def read(adapter, body: str, header: str = HEADER) -> CanonicalApi:
    return adapter.normalize(adapter.parse(header + body, source_label="models.py"))


def types_of(api: CanonicalApi):
    return {t.key: t for t in api.types}


def field(type_, name):
    return next(f for f in type_.fields if f.name == name)


def limits_of(api: CanonicalApi) -> Dict[str, list]:
    return {
        limit["construct"]: limit["locations"]
        for limit in api.extras[PYDANTIC_EXTRAS_KEY]["capability_limits"]
    }


# ===========================================================================
# Adapter surface
# ===========================================================================


def test_adapter_needs_no_toolchain(adapter):
    assert adapter.key == "pydantic"
    assert adapter.required_tools == ()
    assert ".py" in adapter.declared_file_extensions()


def test_declared_constructs_match_the_registry():
    assert set(PYDANTIC_CAPABILITIES.unsupported) == set(LIMIT_DETAILS)
    assert set(capability_for("pydantic").canonical_projection.dropped_constructs) == set(
        LIMIT_DETAILS
    )
    assert PARTIAL_LIMITS <= set(LIMIT_DETAILS)


# ===========================================================================
# No user module is executed
# ===========================================================================


def test_top_level_code_never_runs(adapter, tmp_path):
    sentinel = tmp_path / "executed"
    api = read(
        adapter,
        f"""
import os
open({str(sentinel)!r}, "w").write("ran")
os.system("touch {sentinel}-shell")
raise SystemExit("the module was executed")


class Order(BaseModel):
    id: str
""",
    )
    assert "Order" in types_of(api)
    assert not sentinel.exists()
    assert not (tmp_path / "executed-shell").exists()


def test_a_planted_module_is_never_imported(adapter, monkeypatch):
    imported = []
    real_import = builtins.__import__

    def _spy(name, *args, **kwargs):
        imported.append(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _spy)
    fileset = IntakeFileset.from_members(
        {
            "models.py": (
                "from pydantic import BaseModel\nfrom planted_side_effects import Money\n\n"
                "class Order(BaseModel):\n    total: Money\n"
            ),
            "planted_side_effects.py": (
                "from pydantic import BaseModel\nimport sys\nsys.exit(3)\n\n"
                "class Money(BaseModel):\n    value: int\n"
            ),
        },
        root="models.py",
    )
    api = adapter.normalize(adapter.parse_fileset(fileset))
    assert field(types_of(api)["Order"], "total").type.name == "Money"
    assert "planted_side_effects" not in imported
    assert "planted_side_effects" not in sys.modules


# ===========================================================================
# Constraints and annotations
# ===========================================================================


def test_field_constraints_become_canonical_constraints(adapter):
    api = read(
        adapter,
        """
class Line(BaseModel):
    sku: str = Field(pattern=r"^[A-Z]{3}$")
    quantity: int = Field(gt=0, le=9999)
    price: float = Field(ge=0, lt=1e6, multiple_of=0.01)
    note: str = Field(default="", max_length=200, min_length=0)
    tags: list[str] = Field(min_length=1, max_length=5)
""",
    )
    line = types_of(api)["Line"]
    assert field(line, "sku").constraints.pattern == "^[A-Z]{3}$"
    quantity = field(line, "quantity").constraints
    assert (quantity.exclusive_minimum, quantity.maximum) == (0, 9999)
    price = field(line, "price").constraints
    assert (price.minimum, price.exclusive_maximum, price.multiple_of) == (0, 1e6, 0.01)
    assert field(line, "note").constraints.max_length == 200
    tags = field(line, "tags").constraints
    assert (tags.min_items, tags.max_items) == (1, 5)


def test_annotated_constraints_and_aliases_are_expanded(adapter):
    api = read(
        adapter,
        """
from pydantic import StringConstraints
Sku = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$", min_length=3)]
Percent = Annotated[float, Field(ge=0, le=100)]

class Item(BaseModel):
    sku: Sku
    share: Optional[Percent] = None
""",
    )
    item = types_of(api)["Item"]
    assert field(item, "sku").constraints.pattern == "^[A-Z]{3}$"
    share = field(item, "share")
    assert share.type.nullable is True
    assert (share.constraints.minimum, share.constraints.maximum) == (0, 100)
    assert "Sku" not in types_of(api)


def test_optional_union_and_nested_models(adapter):
    api = read(
        adapter,
        """
class Address(BaseModel):
    city: str

class Customer(BaseModel):
    address: Optional[Address] = None
    home: Address | None
    ident: Union[int, str]
    contact: "Address"
""",
    )
    customer = types_of(api)["Customer"]
    assert (
        field(customer, "address").type.name == "Address"
        and field(customer, "address").type.nullable
    )
    assert field(customer, "home").type.name == "Address" and field(customer, "home").type.nullable
    assert types_of(api)[field(customer, "ident").type.name].kind is TypeKind.UNION
    assert field(customer, "contact").type.name == "Address"


def test_enums_literals_and_defaults(adapter):
    api = read(
        adapter,
        """
from enum import Enum

class Status(str, Enum):
    NEW = "new"
    PAID = "paid"

class Order(BaseModel):
    status: Status = Status.NEW
    kind: Literal["a", "b"] = "a"
    count: int = 3
""",
    )
    types = types_of(api)
    assert [v.value for v in types["Status"].enum_values] == ["new", "paid"]
    order = types["Order"]
    assert field(order, "status").default == "new"
    assert field(order, "kind").constraints.enum == ["a", "b"]
    assert field(order, "count").default == 3 and field(order, "count").type.nullable


def test_inheritance_follows_pydantic_field_order(adapter):
    api = read(
        adapter,
        """
class A(BaseModel):
    x: int
    shared: str = Field(max_length=1)

class B(BaseModel):
    y: int
    shared: str = Field(max_length=2)

class C(A, B):
    z: int
""",
    )
    c = types_of(api)["C"]
    assert {f.name for f in c.fields} == {"x", "y", "z", "shared"}
    assert field(c, "shared").constraints.max_length == 1


def test_generic_instantiated_by_subclassing(adapter):
    api = read(
        adapter,
        """
from typing import Generic, TypeVar
T = TypeVar("T")

class Item(BaseModel):
    id: str

class Page(BaseModel, Generic[T]):
    items: list[T]

class ItemPage(Page[Item]):
    pass
""",
    )
    page = types_of(api)["ItemPage"]
    assert field(page, "items").type.item.name == "Item"


def test_self_reference(adapter):
    api = read(adapter, 'class Node(BaseModel):\n    children: list["Node"] = []\n')
    assert field(types_of(api)["Node"], "children").type.item.name == "Node"


def test_aliases_name_the_wire_field(adapter):
    api = read(
        adapter,
        """
from pydantic import ConfigDict
from pydantic.alias_generators import to_camel

class Explicit(BaseModel):
    order_id: str = Field(alias="orderId")

class Generated(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, extra="forbid")
    created_at: str
""",
    )
    types = types_of(api)
    explicit = field(types["Explicit"], "orderId")
    assert explicit.extras["pydantic_name"] == "order_id"
    assert field(types["Generated"], "createdAt").extras["pydantic_name"] == "created_at"
    assert types["Generated"].extras["pydantic_extra"] == "forbid"


def test_scalar_formats(adapter):
    api = read(
        adapter,
        """
import uuid
from datetime import datetime
from pydantic import EmailStr, AnyUrl

class Contact(BaseModel):
    id: uuid.UUID
    email: EmailStr
    site: AnyUrl
    seen: datetime
""",
    )
    contact = types_of(api)["Contact"]
    assert {f.name: f.constraints.format for f in contact.fields} == {
        "id": "uuid",
        "email": "email",
        "site": "uri",
        "seen": "date-time",
    }


# ===========================================================================
# Declared limits
# ===========================================================================


def test_dynamic_models_are_declared(adapter):
    api = read(
        adapter,
        """
from pydantic import create_model

class Base(BaseModel):
    id: str

Order = create_model("Order", sku=(str, ...))

def factory(name):
    return create_model(name, value=(int, 0))
""",
    )
    assert set(types_of(api)) == {"Base"}
    assert limits_of(api)["pydantic.dynamic_model"] == ["Order", "factory"]


def test_validators_computed_fields_and_hooks_are_declared(adapter):
    api = read(
        adapter,
        """
from pydantic import computed_field, field_validator

class Checked(BaseModel):
    value: int

    @field_validator("value")
    @classmethod
    def even(cls, v):
        return v

    @computed_field
    @property
    def doubled(self) -> int:
        return self.value * 2

class Hooked(BaseModel):
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
""",
    )
    limits = limits_of(api)
    assert limits["pydantic.validator"] == ["Checked"]
    assert limits["pydantic.computed_field"] == ["Checked.doubled"]
    assert limits["pydantic.class_hook"] == ["Hooked"]
    assert [f.name for f in types_of(api)["Checked"].fields] == ["value"]


def test_unknown_types_are_left_out_never_any(adapter):
    api = read(
        adapter,
        """
from pydantic import IPvAnyNetwork
from typing import Callable

class Odd(BaseModel):
    id: str
    network: IPvAnyNetwork
    hook: Callable[[int], int]
""",
    )
    odd = types_of(api)["Odd"]
    assert [f.name for f in odd.fields] == ["id"]
    limits = limits_of(api)
    assert limits["pydantic.unknown_type"] == ["Odd.network"]
    assert limits["pydantic.unrepresentable"] == ["Odd.hook"]


def test_decimal_precision_is_recorded(adapter):
    api = read(
        adapter,
        "from decimal import Decimal\n"
        "class M(BaseModel):\n    amount: Decimal = Field(max_digits=12, decimal_places=2)\n",
    )
    amount = field(types_of(api)["M"], "amount")
    assert amount.type.name == "decimal"
    assert amount.extras["pydantic_decimal"] == {"max_digits": 12, "decimal_places": 2}
    assert limits_of(api)["pydantic.decimal_precision"] == ["M.amount"]


# ===========================================================================
# Detection and intake
# ===========================================================================


def test_detection(adapter):
    assert adapter.detect(DetectionInput(text=HEADER + "class A(BaseModel):\n    x: int\n")).matched
    assert is_pydantic_module("import pydantic\nclass A(pydantic.BaseModel):\n    x: int\n")
    assert not adapter.detect(
        DetectionInput(text="from dataclasses import dataclass\n@dataclass\nclass A:\n    x: int\n")
    ).matched


@pytest.mark.parametrize(
    "text, code",
    [
        ("  \n", "INPUT_EMPTY"),
        ("f\x00r\x00o\x00m", "INPUT_ENCODING_INVALID"),
        (
            "from dataclasses import dataclass\n@dataclass\nclass A:\n    x: int\n",
            "FORMAT_MISMATCH",
        ),
        (
            "from pydantic import BaseModel\nclass A(BaseModel):\n    x: int\n      y: int\n",
            "INPUT_MALFORMED",
        ),
        (
            "from pydantic import BaseModel, Field\nclass A(BaseModel):\n    x: int = Field(ge",
            "INPUT_TRUNCATED",
        ),
        ("from pydantic import TypeAdapter\nTA = TypeAdapter(int)\n", "INPUT_SEMANTIC_INVALID"),
        (
            "from pydantic import BaseModel\nfrom elsewhere import Money\nclass A(BaseModel):\n    m: Money\n",
            "INPUT_REFERENCE_UNRESOLVED",
        ),
    ],
)
def test_rejections_carry_their_taxonomy_code(adapter, text, code):
    with pytest.raises(ImportSourceError) as excinfo:
        adapter.parse(text, source_label="models.py")
    assert excinfo.value.code == code


def test_an_unused_unresolvable_import_costs_nothing(adapter):
    api = read(adapter, "from elsewhere import helper\nclass A(BaseModel):\n    x: int\n")
    assert "A" in types_of(api)


def test_fileset_root_must_be_python(adapter):
    fileset = IntakeFileset.from_members({"README.md": "x", "a.py": "x"}, root="README.md")
    with pytest.raises(ImportSourceError) as excinfo:
        adapter.parse_fileset(fileset)
    assert excinfo.value.code == "INPUT_SEMANTIC_INVALID"
