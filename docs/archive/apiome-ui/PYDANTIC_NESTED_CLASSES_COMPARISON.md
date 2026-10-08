# Pydantic Nested Models: Inner Classes vs Separate Classes

## Question
Should inline properties be converted to inner classes in Python with Pydantic, or is it best to keep things as separate classes?

## Answer: Both Are Valid - It Depends on Your Use Case

Python Pydantic supports both approaches, and each has its own advantages.

---

## Approach 1: Separate Classes (Current Implementation)

### Example
```python
from pydantic import BaseModel
from typing import Optional

class Address(BaseModel):
    """Address details"""
    street: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None

class User(BaseModel):
    """User account"""
    name: str
    email: str
    address: Optional[Address] = None
```

### Advantages ✅
1. **Reusability** - Can use `Address` in multiple models
2. **Clear Namespace** - Models available at module level
3. **Better IDE Support** - Easier to import and reference
4. **Testing** - Easier to test models independently
5. **Documentation** - Models appear in generated API docs
6. **Standard Practice** - Most common pattern in Python/FastAPI

### Disadvantages ❌
1. **Namespace Pollution** - Many classes at module level
2. **Less Obvious Ownership** - Not clear which models are nested
3. **Import Complexity** - Need to import multiple classes

### Best For
- Models reused across multiple parent classes
- Public API models
- Large applications with many models
- FastAPI applications
- When models have independent meaning

---

## Approach 2: Inner Classes (Nested Classes)

### Example
```python
from pydantic import BaseModel
from typing import Optional

class User(BaseModel):
    """User account"""
    
    class Address(BaseModel):
        """Address details"""
        street: Optional[str] = None
        city: Optional[str] = None
        state: Optional[str] = None
    
    name: str
    email: str
    address: Optional[Address] = None
```

### Advantages ✅
1. **Encapsulation** - Nested model belongs to parent
2. **Clean Namespace** - Fewer module-level classes
3. **Clear Ownership** - Obvious that Address belongs to User
4. **Logical Grouping** - Related models grouped together
5. **Reduced Imports** - Import parent, get nested classes

### Disadvantages ❌
1. **No Reusability** - Must access via parent: `User.Address`
2. **Verbosity** - Longer reference: `User.Address` vs `Address`
3. **JSON Schema** - May complicate schema generation
4. **Less Common** - Not the typical Python pattern
5. **IDE Limitations** - Some tools struggle with nested classes

### Best For
- Models only used within one parent
- Private/internal models
- Small to medium applications
- Clear ownership relationships
- When namespace clarity is important

---

## Pydantic Support for Inner Classes

Yes, Pydantic **fully supports** inner classes:

```python
from pydantic import BaseModel

class Company(BaseModel):
    class Employee(BaseModel):
        name: str
        role: str
    
    class Department(BaseModel):
        name: str
        employees: list['Company.Employee']  # Reference nested class
    
    name: str
    departments: list[Department]

# Usage
company = Company(
    name="Tech Corp",
    departments=[
        Company.Department(
            name="Engineering",
            employees=[
                Company.Employee(name="Alice", role="Developer"),
                Company.Employee(name="Bob", role="Manager")
            ]
        )
    ]
)

# Access nested class
employee_type = Company.Employee
print(employee_type)  # <class '__main__.Company.Employee'>
```

---

## Comparison Table

| Feature | Separate Classes | Inner Classes |
|---------|-----------------|---------------|
| **Reusability** | ✅ High | ❌ Low (must use Parent.Inner) |
| **Namespace** | ❌ Cluttered | ✅ Clean |
| **IDE Support** | ✅ Excellent | ⚠️ Good |
| **FastAPI** | ✅ Standard | ⚠️ Works but verbose |
| **Testing** | ✅ Easy | ⚠️ Requires parent import |
| **Documentation** | ✅ Clear | ⚠️ Nested in docs |
| **Python Convention** | ✅ Common | ⚠️ Less common |
| **Ownership Clarity** | ⚠️ Implicit | ✅ Explicit |
| **Import Simplicity** | ❌ Multiple imports | ✅ Single import |

---

## Real-World Examples

### When to Use Separate Classes

```python
# Address is reused by User, Company, Warehouse
class Address(BaseModel):
    street: str
    city: str
    country: str

class User(BaseModel):
    name: str
    home_address: Optional[Address] = None
    work_address: Optional[Address] = None

class Company(BaseModel):
    name: str
    headquarters: Address

class Warehouse(BaseModel):
    code: str
    location: Address
```

### When to Use Inner Classes

```python
# OrderItem is only used within Order
class Order(BaseModel):
    class OrderItem(BaseModel):
        product_id: str
        quantity: int
        price: float
    
    class ShippingAddress(BaseModel):
        recipient: str
        street: str
        city: str
    
    order_id: str
    items: list[OrderItem]
    shipping: ShippingAddress
    total: float
```

---

## Recommendation for Apiome Studio

### Current Implementation: Separate Classes ✅
**Best choice** for the following reasons:

1. **Maximum Flexibility** - Users can refactor later
2. **FastAPI Standard** - Most familiar to users
3. **Reusability** - Models can be reused without modification
4. **Tool Compatibility** - Works with all tooling
5. **Documentation** - Better API docs generation

### Optional Enhancement: Add a Configuration Flag

Allow users to choose their preference:

```typescript
generatePythonDTOs(classes, {
  projectName: 'My API',
  version: '1.0.0',
  nestedClassStyle: 'separate' | 'inner' // New option
});
```

**Separate (Default):**
```python
class Address(BaseModel):
    street: str

class User(BaseModel):
    address: Address
```

**Inner:**
```python
class User(BaseModel):
    class Address(BaseModel):
        street: str
    
    address: Address
```

---

## Python Best Practices

### From PEP 8 and Community Standards

1. **Separate Classes** are preferred for:
   - Public APIs
   - Reusable models
   - FastAPI endpoints
   - Library code

2. **Inner Classes** are acceptable for:
   - Private implementation details
   - Models with strong ownership
   - Configuration classes
   - Factory patterns

### FastAPI Official Examples

FastAPI documentation primarily uses **separate classes**:

```python
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class Item(BaseModel):  # Separate class
    name: str
    price: float

@app.post("/items/")
def create_item(item: Item):
    return item
```

---

## Performance Considerations

**No performance difference** - Both approaches compile to the same runtime behavior. Choice is purely organizational.

---

## Migration Path

If you start with separate classes, moving to inner classes is straightforward:

```python
# Before (Separate)
class Address(BaseModel):
    street: str

class User(BaseModel):
    address: Address

# After (Inner) - Simple refactor
class User(BaseModel):
    class Address(BaseModel):
        street: str
    
    address: Address
```

Reverse migration (inner → separate) is also easy.

---

## Conclusion

### For Apiome Studio: Keep Separate Classes ✅

**Recommendation:** Continue using separate classes as the default because:

1. ✅ **FastAPI Standard** - Expected by users
2. ✅ **Maximum Reusability** - Models can be shared
3. ✅ **Better Tooling** - Full IDE and linter support
4. ✅ **Simpler Imports** - Direct class imports
5. ✅ **Industry Standard** - Most common pattern

### Optional: Add Inner Class Support

Consider adding as an **optional feature** for users who prefer:
- Cleaner namespace
- Explicit ownership
- Smaller applications
- Private/internal models

### Implementation Priority

1. **High Priority:** Ensure separate classes work perfectly ✅ (Done)
2. **Medium Priority:** Add configuration option for inner classes
3. **Low Priority:** Auto-detect when to use inner vs separate

---

## Code Examples for Both Approaches

### Complex Nested Example - Separate Classes

```python
from pydantic import BaseModel
from typing import Optional, List

class PhoneNumber(BaseModel):
    country_code: str
    number: str
    type: str  # mobile, home, work

class Address(BaseModel):
    street: str
    city: str
    state: str
    zip_code: str

class ContactInfo(BaseModel):
    email: str
    phones: List[PhoneNumber]
    address: Optional[Address] = None

class User(BaseModel):
    name: str
    contact: ContactInfo
```

### Complex Nested Example - Inner Classes

```python
from pydantic import BaseModel
from typing import Optional, List

class User(BaseModel):
    class PhoneNumber(BaseModel):
        country_code: str
        number: str
        type: str
    
    class Address(BaseModel):
        street: str
        city: str
        state: str
        zip_code: str
    
    class ContactInfo(BaseModel):
        email: str
        phones: List['User.PhoneNumber']
        address: Optional['User.Address'] = None
    
    name: str
    contact: ContactInfo
```

---

## Final Recommendation

**Keep the current implementation (separate classes)** as the default, and consider adding inner class support as an **optional advanced feature** based on user demand.

The current approach is:
- ✅ Industry standard
- ✅ Most flexible
- ✅ Best for FastAPI
- ✅ Easier to understand
- ✅ Better tooling support

---

**Status:** Separate classes is the correct choice for Apiome Studio
**Optional Enhancement:** Add inner class support as a configuration option
**Priority:** Low (current implementation is best practice)

