# Pydantic Python DTO Generator - Feature Documentation

## Overview

The Python DTO generator now uses **Pydantic v2** to create type-safe, validated data models with comprehensive support for:

- ✅ **allOf** - Inheritance and composition
- ✅ **oneOf** - Discriminated unions  
- ✅ **anyOf** - Non-discriminated unions
- ✅ **Enumerations** - Type-safe enum values using Literal
- ✅ **Regex Patterns** - String validation with regex
- ✅ **Field Constraints** - min/max lengths, numeric ranges, array sizes
- ✅ **Format Validation** - Email, URL, UUID, date/datetime
- ✅ **Nested Models** - Complex object hierarchies
- ✅ **Discriminators** - Polymorphic type resolution

## Generated Code Style

### Before (Dataclasses)
```python
from dataclasses import dataclass

@dataclass
class User:
    name: str
    email: str
```

### After (Pydantic)
```python
from pydantic import BaseModel, Field, EmailStr

class User(BaseModel):
    """User account"""
    name: str = Field(description="User's full name")
    email: EmailStr = Field(description="Email address")
```

## Feature Examples

### 1. Enumerations with Literal

**JSON Schema:**
```json
{
  "type": "string",
  "enum": ["active", "inactive", "suspended"]
}
```

**Generated Python:**
```python
from typing import Literal
from pydantic import BaseModel, Field

class User(BaseModel):
    status: Literal["active", "inactive", "suspended"] = Field(
        description="User account status"
    )
```

### 2. Regex Pattern Validation

**JSON Schema:**
```json
{
  "type": "string",
  "pattern": "^[a-zA-Z0-9_]{3,20}$",
  "minLength": 3,
  "maxLength": 20
}
```

**Generated Python:**
```python
from pydantic import BaseModel, Field

class User(BaseModel):
    username: str = Field(
        description="Username with alphanumeric pattern",
        pattern=r"^[a-zA-Z0-9_]{3,20}$",
        min_length=3,
        max_length=20
    )
```

### 3. Field Constraints

**Numeric Constraints:**
```python
age: int = Field(ge=0, le=150, description="User age")
price: float = Field(ge=0.0, description="Product price")
```

**String Constraints:**
```python
name: str = Field(min_length=1, max_length=100)
```

**Array Constraints:**
```python
tags: List[str] = Field(min_length=1, max_length=10)
```

### 4. Format Validation

**JSON Schema:**
```json
{
  "email": {"type": "string", "format": "email"},
  "website": {"type": "string", "format": "uri"},
  "id": {"type": "string", "format": "uuid"},
  "birthdate": {"type": "string", "format": "date"},
  "created": {"type": "string", "format": "date-time"}
}
```

**Generated Python:**
```python
from datetime import date, datetime
from uuid import UUID
from pydantic import BaseModel, EmailStr, AnyUrl

class User(BaseModel):
    email: EmailStr
    website: AnyUrl
    id: UUID
    birthdate: date
    created: datetime
```

### 5. allOf - Inheritance

**JSON Schema:**
```json
{
  "Animal": {
    "type": "object",
    "required": ["name", "species"],
    "properties": {
      "name": {"type": "string"},
      "species": {"type": "string"}
    }
  },
  "Dog": {
    "allOf": [
      {"$ref": "#/components/schemas/Animal"}
    ],
    "type": "object",
    "required": ["breed"],
    "properties": {
      "breed": {"type": "string"},
      "isGoodBoy": {"type": "boolean", "default": true}
    }
  }
}
```

**Generated Python:**
```python
from pydantic import BaseModel, Field

class Animal(BaseModel):
    """Base animal class"""
    name: str = Field(description="Animal name")
    species: str = Field(description="Species name")

class Dog(Animal):  # Inherits from Animal
    """Dog extends Animal"""
    breed: str = Field(description="Dog breed")
    is_good_boy: bool = Field(default=True, description="Is this a good boy?")
```

### 6. oneOf with Discriminator

**JSON Schema:**
```json
{
  "Circle": {
    "type": "object",
    "required": ["type", "radius"],
    "properties": {
      "type": {"type": "string", "enum": ["circle"]},
      "radius": {"type": "number", "minimum": 0}
    }
  },
  "Rectangle": {
    "type": "object",
    "required": ["type", "width", "height"],
    "properties": {
      "type": {"type": "string", "enum": ["rectangle"]},
      "width": {"type": "number", "minimum": 0},
      "height": {"type": "number", "minimum": 0}
    }
  },
  "Shape": {
    "oneOf": [
      {"$ref": "#/components/schemas/Circle"},
      {"$ref": "#/components/schemas/Rectangle"}
    ],
    "discriminator": {
      "propertyName": "type"
    }
  }
}
```

**Generated Python:**
```python
from typing import Union, Literal
from pydantic import BaseModel, Field

class Circle(BaseModel):
    """Circle shape"""
    type: Literal["circle"] = Field(description="Shape type discriminator")
    radius: float = Field(ge=0, description="Circle radius")

class Rectangle(BaseModel):
    """Rectangle shape"""
    type: Literal["rectangle"] = Field(description="Shape type discriminator")
    width: float = Field(ge=0, description="Rectangle width")
    height: float = Field(ge=0, description="Rectangle height")

Shape = Union[Circle, Rectangle]
# Discriminated union on field: type
```

### 7. anyOf - Non-Discriminated Union

**JSON Schema:**
```json
{
  "anyOf": [
    {"type": "string"},
    {"type": "number"}
  ]
}
```

**Generated Python:**
```python
from typing import Union

StringOrNumber = Union[str, float]
```

### 8. Nested Objects with Validation

**JSON Schema:**
```json
{
  "Company": {
    "type": "object",
    "required": ["name", "employees"],
    "properties": {
      "name": {
        "type": "string",
        "minLength": 1,
        "maxLength": 100
      },
      "employees": {
        "type": "array",
        "minItems": 1,
        "items": {
          "type": "object",
          "properties": {
            "fullName": {"type": "string"},
            "role": {
              "type": "string",
              "enum": ["engineer", "manager", "designer"]
            },
            "salary": {"type": "number", "minimum": 0}
          }
        }
      }
    }
  }
}
```

**Generated Python:**
```python
from typing import List, Literal
from pydantic import BaseModel, Field

class EmployeesItem(BaseModel):
    full_name: str = Field(description="Employee full name")
    role: Literal["engineer", "manager", "designer"] = Field(
        description="Employee role"
    )
    salary: float = Field(ge=0, description="Annual salary")

class Company(BaseModel):
    """Company with employees and address"""
    name: str = Field(
        min_length=1,
        max_length=100,
        description="Company name"
    )
    employees: List[EmployeesItem] = Field(
        min_length=1,
        description="List of employees"
    )
```

## Validation Features

### Automatic Validation

Pydantic automatically validates:
- Type checking (str, int, float, bool)
- Format validation (email, URL, UUID, dates)
- Constraint enforcement (min/max, length, regex)
- Enum value checking
- Required vs optional fields

### Runtime Validation Example

```python
from pydantic import ValidationError

# Valid data
user = User(
    username="john_doe",
    email="john@example.com",
    status="active",
    age=30
)

# Invalid - ValidationError raised
try:
    user = User(
        username="ab",  # Too short (min_length=3)
        email="invalid",  # Not a valid email
        status="unknown",  # Not in enum
        age=200  # Exceeds maximum (150)
    )
except ValidationError as e:
    print(e.json())
```

## Discriminators

### How Discriminators Work

When using `oneOf` with a discriminator, Pydantic can automatically determine which model to use based on a discriminator field:

```python
from pydantic import Field

# Parse JSON with discriminator
shape_data = {"type": "circle", "radius": 5.0}
shape = Shape.model_validate(shape_data)  # Returns Circle instance

shape_data = {"type": "rectangle", "width": 10, "height": 5}
shape = Shape.model_validate(shape_data)  # Returns Rectangle instance
```

### Benefits
- ✅ Type-safe polymorphism
- ✅ Automatic type resolution
- ✅ Clear inheritance hierarchies
- ✅ Runtime validation

## Configuration

### Model Config

Classes can include Pydantic configuration:

```python
class User(BaseModel):
    model_config = ConfigDict(discriminator='type')
```

### Common Config Options
- `discriminator`: Field name for discriminated unions
- `str_strip_whitespace`: Strip whitespace from strings
- `validate_assignment`: Validate on attribute assignment
- `use_enum_values`: Use enum values instead of enum instances

## Type Mapping

| JSON Schema | Python Type | Pydantic Type |
|------------|-------------|---------------|
| string | str | str |
| string (email) | str | EmailStr |
| string (uri/url) | str | AnyUrl |
| string (uuid) | str | UUID |
| string (date) | str | date |
| string (date-time) | str | datetime |
| string (enum) | str | Literal[...] |
| integer | int | int |
| number | float | float |
| boolean | bool | bool |
| array | list | List[T] |
| object | dict | Nested Model |
| oneOf | - | Union[...] |
| anyOf | - | Union[...] |
| allOf | - | Inheritance |

## Benefits of Pydantic

1. **Type Safety**: Full static type checking with mypy
2. **Runtime Validation**: Automatic data validation
3. **IDE Support**: Excellent autocomplete and type hints
4. **Serialization**: Easy JSON/dict conversion
5. **Performance**: Fast validation using Rust (pydantic-core)
6. **Ecosystem**: Wide adoption, great documentation
7. **FastAPI Integration**: Native support in FastAPI
8. **JSON Schema**: Can generate JSON Schema from models

## Usage in FastAPI

```python
from fastapi import FastAPI
from pydantic import BaseModel, EmailStr

app = FastAPI()

class User(BaseModel):
    username: str
    email: EmailStr

@app.post("/users/")
def create_user(user: User):
    # Automatic validation and serialization
    return user
```

## Migration from Dataclasses

### Old (Dataclasses)
```python
from dataclasses import dataclass

@dataclass
class User:
    name: str
    email: str
```

### New (Pydantic)
```python
from pydantic import BaseModel, EmailStr

class User(BaseModel):
    name: str
    email: EmailStr
```

### Key Differences
- No `@dataclass` decorator needed
- Inherit from `BaseModel`
- Use `Field()` for constraints
- Automatic validation
- Better serialization

## Testing

See `test-pydantic-dto.ts` for comprehensive test examples covering:
- Enums and regex patterns
- allOf inheritance
- oneOf with discriminators
- anyOf unions
- Complex nested structures
- Field constraints

## Next Steps

Future enhancements could include:
- Custom validators
- Computed fields
- Model serialization options
- Database integration (SQLModel)
- Multiple file output (one model per file)
- Pydantic v2 advanced features

---

**Generated by Apiome Studio**

