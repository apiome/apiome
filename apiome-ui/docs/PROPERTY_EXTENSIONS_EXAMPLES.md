# Property Extensions - Visual Examples

## Example 1: Basic String Property with Extensions

### Property Configuration
```
Property Name: email
Type: string
Format: email
Description: User's email address
```

### Extensions Added
```json
{
  "x-display-name": "Email Address",
  "x-help-text": "Primary contact email for the user",
  "x-searchable": true,
  "x-pii": true
}
```

### Resulting OpenAPI Schema
```yaml
email:
  type: string
  format: email
  description: User's email address
  x-display-name: Email Address
  x-help-text: Primary contact email for the user
  x-searchable: true
  x-pii: true
```

---

## Example 2: Number Property with Validation Extensions

### Property Configuration
```
Property Name: age
Type: number
Minimum: 0
Maximum: 150
```

### Extensions Added
```json
{
  "x-ui-component": "number-spinner",
  "x-validation-level": "strict",
  "x-error-message": "Age must be between 0 and 150"
}
```

### Resulting OpenAPI Schema
```yaml
age:
  type: number
  minimum: 0
  maximum: 150
  x-ui-component: number-spinner
  x-validation-level: strict
  x-error-message: Age must be between 0 and 150
```

---

## Example 3: Array Property with Metadata Extensions

### Property Configuration
```
Property Name: tags
Type: array
Items Type: string
Min Items: 1
Max Items: 10
```

### Extensions Added
```json
{
  "x-ui-widget": "tag-input",
  "x-suggestions": ["important", "urgent", "review", "archived"],
  "x-allow-custom": true
}
```

### Resulting OpenAPI Schema
```yaml
tags:
  type: array
  items:
    type: string
  minItems: 1
  maxItems: 10
  x-ui-widget: tag-input
  x-suggestions:
    - important
    - urgent
    - review
    - archived
  x-allow-custom: true
```

---

## Example 4: Object Property with Complex Extensions

### Property Configuration
```
Property Name: address
Type: object
Additional Properties: false
```

### Extensions Added
```json
{
  "x-ui-layout": "vertical",
  "x-validation": {
    "strategy": "on-blur",
    "required-fields": ["street", "city", "zipCode"]
  },
  "x-autocomplete": {
    "enabled": true,
    "service": "google-places-api"
  }
}
```

### Resulting OpenAPI Schema
```yaml
address:
  type: object
  additionalProperties: false
  x-ui-layout: vertical
  x-validation:
    strategy: on-blur
    required-fields:
      - street
      - city
      - zipCode
  x-autocomplete:
    enabled: true
    service: google-places-api
```

---

## Example 5: Property with Deprecation Extensions

### Property Configuration
```
Property Name: oldField
Type: string
Deprecated: true
```

### Extensions Added
```json
{
  "x-deprecated-in": "v2.0.0",
  "x-removed-in": "v3.0.0",
  "x-replacement": "newField",
  "x-migration-guide": "https://docs.example.com/migration/v2-to-v3"
}
```

### Resulting OpenAPI Schema
```yaml
oldField:
  type: string
  deprecated: true
  x-deprecated-in: v2.0.0
  x-removed-in: v3.0.0
  x-replacement: newField
  x-migration-guide: https://docs.example.com/migration/v2-to-v3
```

---

## Example 6: Enum Property with UI Extensions

### Property Configuration
```
Property Name: priority
Type: string
Enum: ["low", "medium", "high", "critical"]
```

### Extensions Added
```json
{
  "x-enum-labels": {
    "low": "Low Priority",
    "medium": "Medium Priority",
    "high": "High Priority",
    "critical": "Critical Priority"
  },
  "x-enum-colors": {
    "low": "#4CAF50",
    "medium": "#FFC107",
    "high": "#FF9800",
    "critical": "#F44336"
  }
}
```

### Resulting OpenAPI Schema
```yaml
priority:
  type: string
  enum:
    - low
    - medium
    - high
    - critical
  x-enum-labels:
    low: Low Priority
    medium: Medium Priority
    high: High Priority
    critical: Critical Priority
  x-enum-colors:
    low: "#4CAF50"
    medium: "#FFC107"
    high: "#FF9800"
    critical: "#F44336"
```

---

## Example 7: Boolean Property with Feature Flags

### Property Configuration
```
Property Name: emailNotifications
Type: boolean
Default: true
```

### Extensions Added
```json
{
  "x-feature-flag": "enable-notifications",
  "x-requires-permission": "manage-settings",
  "x-ui-label": "Enable Email Notifications",
  "x-ui-description": "Receive email updates about your account"
}
```

### Resulting OpenAPI Schema
```yaml
emailNotifications:
  type: boolean
  default: true
  x-feature-flag: enable-notifications
  x-requires-permission: manage-settings
  x-ui-label: Enable Email Notifications
  x-ui-description: Receive email updates about your account
```

---

## Example 8: Property with Custom Validation Extensions

### Property Configuration
```
Property Name: username
Type: string
Min Length: 3
Max Length: 20
Pattern: ^[a-zA-Z0-9_]+$
```

### Extensions Added
```json
{
  "x-async-validation": {
    "endpoint": "/api/validate/username",
    "debounce": 500
  },
  "x-reserved-values": ["admin", "root", "system"],
  "x-case-sensitive": false
}
```

### Resulting OpenAPI Schema
```yaml
username:
  type: string
  minLength: 3
  maxLength: 20
  pattern: ^[a-zA-Z0-9_]+$
  x-async-validation:
    endpoint: /api/validate/username
    debounce: 500
  x-reserved-values:
    - admin
    - root
    - system
  x-case-sensitive: false
```

---

## Example 9: Date Property with Formatting Extensions

### Property Configuration
```
Property Name: birthDate
Type: string
Format: date
```

### Extensions Added
```json
{
  "x-date-format": "MM/DD/YYYY",
  "x-date-picker": {
    "minDate": "1900-01-01",
    "maxDate": "today",
    "yearRange": "-120:+0"
  },
  "x-timezone-aware": false
}
```

### Resulting OpenAPI Schema
```yaml
birthDate:
  type: string
  format: date
  x-date-format: MM/DD/YYYY
  x-date-picker:
    minDate: "1900-01-01"
    maxDate: today
    yearRange: "-120:+0"
  x-timezone-aware: false
```

---

## Example 10: File Upload Property with Extensions

### Property Configuration
```
Property Name: profileImage
Type: string
Format: binary
```

### Extensions Added
```json
{
  "x-file-types": ["image/jpeg", "image/png", "image/gif"],
  "x-max-file-size": 5242880,
  "x-storage-service": "s3",
  "x-image-dimensions": {
    "minWidth": 200,
    "minHeight": 200,
    "maxWidth": 2000,
    "maxHeight": 2000
  }
}
```

### Resulting OpenAPI Schema
```yaml
profileImage:
  type: string
  format: binary
  x-file-types:
    - image/jpeg
    - image/png
    - image/gif
  x-max-file-size: 5242880
  x-storage-service: s3
  x-image-dimensions:
    minWidth: 200
    minHeight: 200
    maxWidth: 2000
    maxHeight: 2000
```

---

## UI Screenshots (Conceptual)

### Extensions Editor in Property Dialog

```
┌─────────────────────────────────────────────────────────────┐
│ Edit Property                                    [Form] [JSON]│
├─────────────────────────────────────────────────────────────┤
│                                                               │
│ Property Name: email                                          │
│ Type: string        [ ] Array                                 │
│ Format: email                                                 │
│                                                               │
│ ... (other property fields) ...                              │
│                                                               │
│ ┌───────────────────────────────────────────────────────┐   │
│ │ Extensions                                             │   │
│ │                                                        │   │
│ │ Add custom x- prefixed properties per OpenAPI 3.1     │   │
│ │ specification. Values can be any valid JSON.          │   │
│ │                                                        │   │
│ │ ┌─────────────┬──────────────────────┬──────────┐    │   │
│ │ │ x-searchable│ true                 │ [+ Add]  │    │   │
│ │ └─────────────┴──────────────────────┴──────────┘    │   │
│ │                                                        │   │
│ │ ┌───────────────────────────────────────────────┐    │   │
│ │ │ x-display-name                          [🗑️]   │    │   │
│ │ │ "Email Address"                               │    │   │
│ │ ├───────────────────────────────────────────────┤    │   │
│ │ │ x-pii                                   [🗑️]   │    │   │
│ │ │ true                                          │    │   │
│ │ └───────────────────────────────────────────────┘    │   │
│ └───────────────────────────────────────────────────────┘   │
│                                                               │
├─────────────────────────────────────────────────────────────┤
│                                    [Cancel]  [Save Property] │
└─────────────────────────────────────────────────────────────┘
```

---

## Best Practices Summary

1. **Naming Convention**: Use kebab-case with "x-" prefix
   - ✅ `x-display-name`, `x-ui-component`, `x-validation-level`
   - ❌ `x_display_name`, `xDisplayName`, `x-DisplayName`

2. **Organize by Purpose**: Group related extensions
   - UI extensions: `x-ui-*`
   - Validation: `x-validation-*`
   - Internal: `x-internal-*`

3. **Use Appropriate Types**: Match value type to purpose
   - Booleans for flags
   - Numbers for limits
   - Objects for complex config
   - Arrays for lists

4. **Document Custom Extensions**: Maintain a registry of your organization's extensions

5. **Keep it Simple**: Only add extensions when necessary
   - Don't duplicate standard OpenAPI properties
   - Don't over-engineer with excessive metadata

