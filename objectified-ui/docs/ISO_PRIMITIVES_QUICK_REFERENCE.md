# ISO Primitives Quick Reference Guide

## Migration Applied Successfully ✅

The database has been preloaded with **36 industry-standard ISO primitives**.

## Quick Stats

| Metric | Value |
|--------|-------|
| Total Primitives | 36 |
| String Primitives | 20 |
| Integer Primitives | 5 |
| Number Primitives | 4 |
| Array Primitives | 4 |
| Boolean Primitives | 1 |
| Object Primitives | 1 |
| Null Primitives | 1 |
| Categories | 7 |

## String Primitives (20)

**Communication**
- Email Address (RFC 5321/5322)
- Phone Number E.164 (ITU-T)

**Identifiers**
- UUID (RFC 4122)
- Country Code (ISO 3166-1)
- Language Code (ISO 639-1)
- Currency Code (ISO 4217)

**Web/Network**
- URL (RFC 1738)
- URI (RFC 3986)
- IPv4 Address (RFC 791)
- IPv6 Address (RFC 4291)

**Financial**
- IBAN (ISO 13616)
- Monetary Amount

**Temporal**
- Date (ISO 8601)
- Date-Time (ISO 8601)
- Time (ISO 8601)
- Duration (ISO 8601)

**Data/Encoding**
- SHA-256 Hash
- Base64 String
- JSON String

**Miscellaneous**
- Boolean String
- Log Level

## Numeric Primitives (9)

**Integer (5)**
- Integer
- Positive Integer (≥1)
- Non-Negative Integer (≥0)
- Percentage Integer (0-100)
- HTTP Status Code (100-599)

**Decimal Number (4)**
- Decimal Number
- Percentage Decimal (0.0-100.0)
- Probability (0.0-1.0)
- Monetary Amount

## Collection Primitives (5)

**Arrays (4)**
- String Array
- Integer Array
- Number Array
- Boolean Array

**Objects (1)**
- JSON Object

## Simple Primitives (2)

- Boolean
- Null Value

## Quick Start

### 1. List All Available Primitives
```bash
curl -H "X-API-Key: YOUR_API_KEY" \
  http://localhost:8000/v1/primitives/YOUR_TENANT_SLUG
```

### 2. Filter by Category
```bash
# Get all string primitives
curl -H "X-API-Key: YOUR_API_KEY" \
  "http://localhost:8000/v1/primitives/YOUR_TENANT_SLUG?category=string"

# Get all number primitives
curl -H "X-API-Key: YOUR_API_KEY" \
  "http://localhost:8000/v1/primitives/YOUR_TENANT_SLUG?category=number"
```

### 3. Get Specific Primitive
```bash
curl -H "X-API-Key: YOUR_API_KEY" \
  http://localhost:8000/v1/primitives/YOUR_TENANT_SLUG/PRIMITIVE_ID
```

### 4. Use in JSON Schema
```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "properties": {
    "email": {
      "$ref": "#/definitions/Email Address"
    },
    "country": {
      "$ref": "#/definitions/Country Code (ISO 3166-1)"
    },
    "birthDate": {
      "$ref": "#/definitions/Date (ISO 8601)"
    },
    "salary": {
      "$ref": "#/definitions/Monetary Amount"
    },
    "active": {
      "$ref": "#/definitions/Boolean"
    }
  }
}
```

## ISO & RFC Standards Covered

- ✅ JSON Schema (IETF)
- ✅ ISO 8601 (Date/Time)
- ✅ ISO 3166-1 (Countries)
- ✅ ISO 639-1 (Languages)
- ✅ ISO 4217 (Currencies)
- ✅ ISO 13616 (IBAN)
- ✅ RFC 791 (IPv4)
- ✅ RFC 1738 (URL)
- ✅ RFC 3986 (URI)
- ✅ RFC 4122 (UUID)
- ✅ RFC 4291 (IPv6)
- ✅ RFC 4648 (Base64)
- ✅ RFC 5321/5322 (Email)
- ✅ ITU-T E.164 (Phone)

## Database Commands

### View All System Primitives
```sql
SELECT name, category FROM odb.primitives 
WHERE is_system = true 
ORDER BY category, name;
```

### Count by Category
```sql
SELECT category, COUNT(*) 
FROM odb.primitives WHERE is_system = true 
GROUP BY category;
```

### Search by Tag
```sql
SELECT name, category, tags 
FROM odb.primitives 
WHERE tags @> ARRAY['iso-standard'] 
AND is_system = true;
```

### Get Primitive Details
```sql
SELECT id, name, category, description, schema, tags 
FROM odb.primitives 
WHERE name = 'Email Address' 
AND is_system = true;
```

## File References

- **Migration**: `objectified-db/scripts/20260124-140000.sql`
- **Documentation**: `ISO_PRIMITIVES_PRELOAD.md`
- **Implementation**: `ISO_PRIMITIVES_IMPLEMENTATION_SUMMARY.md`
- **Tests**: `objectified-rest/test_iso_primitives_preload.py`

## Key Points

✓ All primitives are **system primitives** (immutable)  
✓ All primitives are **enabled** by default  
✓ All primitives are **public** within tenant scope  
✓ All primitives support **soft delete** for audit trail  
✓ All primitives are **indexed** for efficient queries  
✓ All primitives follow **international standards**  
✓ Custom primitives can be added on top of these  
✓ All tenants automatically receive these primitives  

## Need Help?

1. Check `ISO_PRIMITIVES_PRELOAD.md` for detailed information
2. Review test file: `test_iso_primitives_preload.py`
3. Query database directly for schema details
4. Use REST API to explore available primitives
