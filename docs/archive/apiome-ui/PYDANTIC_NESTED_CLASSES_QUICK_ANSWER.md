# Quick Answer: Inner Classes vs Separate Classes in Pydantic

## Short Answer

**Both are possible in Pydantic**, but **separate classes are recommended** for Apiome Studio.

---

## Can You Use Inner Classes?

**YES** - Pydantic fully supports inner/nested classes:

```python
class User(BaseModel):
    class Address(BaseModel):  # Inner class
        street: str
        city: str
    
    name: str
    address: Address
```

---

## Should You Use Inner Classes?

**It Depends**, but for Apiome Studio: **Use Separate Classes**

---

## Quick Comparison

| | Separate Classes | Inner Classes |
|-|-----------------|---------------|
| **Reusability** | ✅ Can reuse anywhere | ❌ Must use `Parent.Nested` |
| **FastAPI Standard** | ✅ Industry norm | ⚠️ Works but uncommon |
| **Clean Namespace** | ❌ Many classes | ✅ Fewer classes |
| **IDE Support** | ✅ Excellent | ✅ Good |
| **Import** | `from models import Address` | `from models import User; User.Address` |

---

## Examples

### Separate Classes (Recommended)
```python
class Address(BaseModel):
    street: str
    city: str

class User(BaseModel):
    name: str
    address: Address  # Simple reference

# Use anywhere
user_addr: Address = ...
company_addr: Address = ...
```

### Inner Classes (Alternative)
```python
class User(BaseModel):
    class Address(BaseModel):
        street: str
        city: str
    
    name: str
    address: Address  # Same name, scoped to User

# Must use qualified name elsewhere
user_addr: User.Address = ...
```

---

## When to Use Each

### Use Separate Classes When:
- ✅ Building APIs (FastAPI, Django Ninja, etc.)
- ✅ Models might be reused
- ✅ Following Python/FastAPI conventions
- ✅ Working in teams
- ✅ **Default choice for Apiome Studio**

### Use Inner Classes When:
- ✅ Model is only used by one parent
- ✅ Want clear ownership
- ✅ Prefer cleaner namespace
- ✅ Building small internal tools
- ✅ Strong encapsulation needs

---

## Real Example

### Separate (Current Apiome)
```python
class OrderItem(BaseModel):
    product_id: str
    quantity: int
    price: float

class Order(BaseModel):
    order_id: str
    items: List[OrderItem]  # Reusable
    total: float

class ShoppingCart(BaseModel):
    items: List[OrderItem]  # Same class reused!
```

### Inner (Alternative)
```python
class Order(BaseModel):
    class OrderItem(BaseModel):
        product_id: str
        quantity: int
        price: float
    
    order_id: str
    items: List[OrderItem]
    total: float

class ShoppingCart(BaseModel):
    # Must use Order.OrderItem or define own inner class
    items: List[Order.OrderItem]  # Less clean
```

---

## Recommendation

### For Apiome Studio: **Keep Separate Classes** ✅

**Why?**
1. Industry standard for FastAPI
2. Maximum flexibility
3. Better code reuse
4. Simpler imports
5. What users expect

### Optional: Add Inner Class Option

Could add as a **future feature** with a config flag:

```typescript
generatePythonDTOs(classes, {
  nestedClassStyle: 'separate' | 'inner'  // Default: 'separate'
});
```

But **not urgent** - current approach is best practice.

---

## Python Community Consensus

From FastAPI docs, Pydantic docs, and Python style guides:

**"Prefer separate classes at module level for public models"**

Inner classes are fine for:
- Private implementation details
- Configuration objects
- Factory patterns
- Strong encapsulation needs

But for API models: **Separate classes are the standard.**

---

## Bottom Line

✅ **Current implementation is correct**
✅ **Separate classes are best practice**
✅ **Inner classes are possible but optional**
✅ **No need to change current behavior**

---

**Recommendation:** Keep using separate classes (current implementation is correct)
**Optional Future:** Add inner class support as advanced feature if users request it
**Priority:** Very Low - current approach is industry standard

