# Pydantic Python DTO Generator - Quick Reference

## JSON Schema → Pydantic Mapping

### Basic Types
| JSON Schema | Pydantic |
|------------|----------|
| `{"type": "string"}` | `str` |
| `{"type": "integer"}` | `int` |
| `{"type": "number"}` | `float` |
| `{"type": "boolean"}` | `bool` |

### Enums
```json
{"type": "string", "enum": ["A", "B", "C"]}
```
↓
```python
from typing import Literal
status: Literal["A", "B", "C"]
```

### Regex Pattern
```json
{
  "type": "string",
  "pattern": "^[a-z]+$",
  "minLength": 3,
  "maxLength": 20
}
```
↓
```python
from pydantic import Field
name: str = Field(pattern=r"^[a-z]+$", min_length=3, max_length=20)
```

### Email
```json
{"type": "string", "format": "email"}
```
↓
```python
from pydantic import EmailStr
email: EmailStr
```

### URL
```json
{"type": "string", "format": "uri"}
```
↓
```python
from pydantic import AnyUrl
website: AnyUrl
```

### UUID
```json
{"type": "string", "format": "uuid"}
```
↓
```python
from uuid import UUID
id: UUID
```

### Date/DateTime
```json
{"type": "string", "format": "date"}
{"type": "string", "format": "date-time"}
```
↓
```python
from datetime import date, datetime
birthdate: date
created_at: datetime
```

### Numeric Constraints
```json
{
  "type": "integer",
  "minimum": 0,
  "maximum": 100
}
```
↓
```python
from pydantic import Field
age: int = Field(ge=0, le=100)
```

### Arrays
```json
{
  "type": "array",
  "items": {"type": "string"},
  "minItems": 1,
  "maxItems": 10
}
```
↓
```python
from typing import List
from pydantic import Field
tags: List[str] = Field(min_length=1, max_length=10)
```

### allOf (Inheritance)
```json
{
  "Dog": {
    "allOf": [
      {"$ref": "#/components/schemas/Animal"}
    ],
    "properties": {
      "breed": {"type": "string"}
    }
  }
}
```
↓
```python
class Dog(Animal):
    breed: str
```

### oneOf (Discriminated Union)
```json
{
  "Shape": {
    "oneOf": [
      {"$ref": "#/components/schemas/Circle"},
      {"$ref": "#/components/schemas/Square"}
    ],
    "discriminator": {
      "propertyName": "type"
    }
  }
}
```
↓
```python
from typing import Union
Shape = Union[Circle, Square]
# Discriminated union on field: type
```

### anyOf (Union)
```json
{
  "anyOf": [
    {"type": "string"},
    {"type": "number"}
  ]
}
```
↓
```python
from typing import Union
Value = Union[str, float]
```

### Optional Fields
```json
{
  "properties": {
    "name": {"type": "string"}
  },
  "required": []
}
```
↓
```python
from typing import Optional
from pydantic import Field
name: Optional[str] = Field(default=None)
```

### Default Values
```json
{
  "type": "boolean",
  "default": true
}
```
↓
```python
from pydantic import Field
active: bool = Field(default=True)
```

## Field() Arguments

| Constraint | Field() Arg | Example |
|-----------|-------------|---------|
| Pattern | `pattern` | `Field(pattern=r"^[a-z]+$")` |
| Min Length | `min_length` | `Field(min_length=3)` |
| Max Length | `max_length` | `Field(max_length=20)` |
| Minimum | `ge` | `Field(ge=0)` |
| Maximum | `le` | `Field(le=100)` |
| Description | `description` | `Field(description="...")` |
| Default | `default` | `Field(default=None)` |

## Usage Example

### FastAPI
```python
from fastapi import FastAPI
from pydantic import BaseModel, EmailStr, Field

app = FastAPI()

class User(BaseModel):
    username: str = Field(min_length=3, max_length=20)
    email: EmailStr
    age: int = Field(ge=0, le=150)

@app.post("/users/")
def create_user(user: User):
    return user
```

### Validation
```python
from pydantic import ValidationError

try:
    user = User(
        username="ab",  # Too short
        email="invalid",  # Not an email
        age=200  # Too high
    )
except ValidationError as e:
    print(e.json())
```

### Serialization
```python
user = User(username="john", email="john@example.com", age=30)

# To dict
user_dict = user.model_dump()

# To JSON
user_json = user.model_dump_json()

# From dict
user = User.model_validate(user_dict)

# From JSON
user = User.model_validate_json(user_json)
```

## Common Patterns

### Nested Models
```python
class Address(BaseModel):
    street: str
    city: str

class User(BaseModel):
    name: str
    address: Address
```

### List of Models
```python
from typing import List

class Company(BaseModel):
    employees: List[User]
```

### Discriminated Union
```python
from typing import Union, Literal

class Circle(BaseModel):
    type: Literal["circle"]
    radius: float

class Square(BaseModel):
    type: Literal["square"]
    side: float

Shape = Union[Circle, Square]
```

### Inheritance
```python
class Animal(BaseModel):
    name: str

class Dog(Animal):
    breed: str
```

## Tips

1. **Always use Field()** for constraints and descriptions
2. **Use Literal** for enums instead of string enums
3. **EmailStr and AnyUrl** for validated formats
4. **Optional[T]** for nullable fields
5. **List[T]** instead of list[T] for Python < 3.9
6. **ConfigDict** for model configuration
7. **Union** for oneOf/anyOf schemas

## Resources

- [Pydantic Docs](https://docs.pydantic.dev)
- [FastAPI Docs](https://fastapi.tiangolo.com)
- [JSON Schema](https://json-schema.org)
- [Type Hints](https://docs.python.org/3/library/typing.html)

---

**Generated by Apiome Studio**

