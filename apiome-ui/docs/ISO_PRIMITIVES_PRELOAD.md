# ISO Standard Primitives Preload

## Overview

The primitives table has been preloaded with **36 industry-standard ISO primitives** covering all major JSON Schema data types and formats. These primitives follow JSON Schema specifications and international standards (ISO, RFC, ITU-T).

## Migration Details

- **Migration File**: `20260124-140000.sql`
- **Total Primitives Loaded**: 36 (all tenants)
- **System Flag**: `is_system = true` (built-in, immutable primitives)
- **Public Flag**: `is_public = true` (visible to all users)

## Primitives by Category

### String Primitives (20 total)

| Name | Standard | Description |
|------|----------|-------------|
| Email Address | RFC 5321/5322 | Valid email in standard format |
| UUID | RFC 4122 | Universally unique identifier |
| Uniform Resource Identifier (URI) | RFC 3986 | Full URI including URLs and URNs |
| Uniform Resource Locator (URL) | RFC 1738 | HTTP(S), FTP, and other scheme-based URLs |
| Date (ISO 8601) | ISO 8601 | Calendar date: YYYY-MM-DD |
| Date-Time (ISO 8601) | ISO 8601 | Date-time with timezone: YYYY-MM-DDTHH:mm:ss[.sss][Z\|±HH:mm] |
| Time (ISO 8601) | ISO 8601 | Time of day: HH:mm:ss[.sss] |
| Duration (ISO 8601) | ISO 8601 | Period: P[n]Y[n]M[n]DT[n]H[n]M[n]S |
| IPv4 Address | RFC 791 | IPv4 in dotted decimal: 0.0.0.0 to 255.255.255.255 |
| IPv6 Address | RFC 4291 | IPv6 in standard notation |
| Phone Number (E.164) | ITU-T E.164 | International phone: +[1-9]{1,15} |
| International Bank Account Number (IBAN) | ISO 13616 | IBAN: CC##KKKK... |
| Country Code (ISO 3166-1) | ISO 3166-1 | Two-letter country code |
| Language Code (ISO 639-1) | ISO 639-1 | Two-letter language code |
| Currency Code (ISO 4217) | ISO 4217 | Three-letter currency code |
| SHA-256 Hash | - | 256-bit cryptographic hash (64 hex chars) |
| Base64 String | RFC 4648 | Base64 encoded binary data |
| JSON String | - | String containing valid JSON |
| Boolean String | - | String enum: "true" or "false" |
| Log Level | - | Enum: DEBUG, INFO, WARN, ERROR, FATAL, CRITICAL |

### Integer Primitives (5 total)

| Name | Range | Description |
|------|-------|-------------|
| Integer | -2^53+1 to 2^53-1 | Whole number without fractional part |
| Positive Integer | ≥ 1 | Integer greater than zero |
| Non-Negative Integer | ≥ 0 | Integer greater than or equal to zero |
| Percentage (Integer) | 0-100 | Integer percentage value |
| HTTP Status Code | 100-599 | Standard HTTP response codes |

### Number Primitives (4 total)

| Name | Range | Description |
|------|-------|-------------|
| Decimal Number | Any | Floating-point number |
| Percentage (Decimal) | 0.0-100.0 | Decimal percentage value |
| Probability | 0.0-1.0 | Probability likelihood value |
| Monetary Amount | ≥ 0 | Decimal monetary amount |

### Boolean Primitives (1 total)

| Name | Description |
|------|-------------|
| Boolean | True or false boolean value |

### Array Primitives (4 total)

| Name | Item Type | Description |
|------|-----------|-------------|
| String Array | string | Array of text values |
| Integer Array | integer | Array of whole numbers |
| Number Array | number | Array of floating-point numbers |
| Boolean Array | boolean | Array of true/false values |

### Object Primitives (1 total)

| Name | Description |
|------|-------------|
| JSON Object | Untyped key-value pairs |

### Null Primitives (1 total)

| Name | Description |
|------|-------------|
| Null Value | Represents absence of data |

## Tags Classification

All primitives are tagged with relevant categories for easy discovery:

- **ISO-Standard Tags**: `iso-standard` (20+ primitives)
- **Domain Tags**: `email`, `phone`, `contact`, `finance`, `banking`, `currency`, `web`, `network`, `security`, etc.
- **Type Tags**: `string`, `integer`, `number`, `boolean`, `array`, `object`, `numeric`, `decimal`, `list`, `collection`
- **Purpose Tags**: `identifier`, `id`, `uuid`, `hash`, `encoding`, `cryptography`, `temporal`, `communication`, `geographic`

## Usage Examples

### List All System Primitives

```bash
curl -H "X-API-Key: your-api-key" \
  http://localhost:8000/v1/primitives/your-tenant-slug
```

### List Primitives by Category

```bash
curl -H "X-API-Key: your-api-key" \
  "http://localhost:8000/v1/primitives/your-tenant-slug?category=string"
```

### Create Schema Using Preloaded Primitives

```json
{
  "type": "object",
  "properties": {
    "email": {
      "$ref": "#/definitions/Email Address"
    },
    "country": {
      "$ref": "#/definitions/Country Code (ISO 3166-1)"
    },
    "amount": {
      "$ref": "#/definitions/Monetary Amount"
    },
    "active": {
      "$ref": "#/definitions/Boolean"
    }
  }
}
```

## Standards Compliance

The preloaded primitives follow these international standards:

- **JSON Schema**: Latest IETF draft specifications
- **ISO 8601**: Date and time formats
- **ISO 3166-1**: Country codes (alpha-2)
- **ISO 639-1**: Language codes
- **ISO 4217**: Currency codes
- **ISO 13616**: IBAN format
- **RFC 791**: IPv4 addresses
- **RFC 1738**: URL syntax
- **RFC 3986**: URI syntax
- **RFC 4122**: UUID format
- **RFC 4291**: IPv6 addresses
- **RFC 4648**: Base64 encoding
- **RFC 5321/5322**: Email addresses
- **ITU-T E.164**: Phone numbers

## Database Metrics

```sql
-- Total system primitives
SELECT COUNT(*) FROM apiome.primitives WHERE is_system = true;
-- Result: 36

-- Distribution by category
SELECT category, COUNT(*) FROM apiome.primitives WHERE is_system = true GROUP BY category;

-- All primitives are enabled by default
SELECT COUNT(*) FROM apiome.primitives WHERE is_system = true AND enabled = true;
-- Result: 36
```

## Notes

- All system primitives are **immutable** by design (prevent accidental modification)
- Primitives are **tenant-scoped** but system primitives apply to all tenants
- Soft-delete support ensures audit trail
- Usage tracking is enabled for all primitives
- Indexed by tenant, category, tags, and created date for fast queries
- Tags use GIN index for efficient array queries

## Next Steps

1. **Custom Primitives**: Users can create tenant-specific primitives on top of these standards
2. **Primitive Extensions**: Extend with domain-specific primitives as needed
3. **Import/Export**: Use JSON Schema import to add additional primitives
4. **Versioning**: Track primitive usage and deprecation as standards evolve
