# Property Extensions Quick Reference

## What are Property Extensions?

Property extensions are custom x- prefixed properties that you can add to any property in your schema. They allow you to attach additional metadata that can be used by tools, documentation generators, or custom validation logic.

## How to Add Extensions to a Property

### Step 1: Open Property Editor
- Click on a property in a class to edit it, OR
- Add a new property to a class

### Step 2: Scroll to Extensions Section
- The Extensions section is located at the bottom of the property form
- It's in a highlighted gray box

### Step 3: Add an Extension
1. Enter a key in the "Key" field (must start with `x-`)
   - Example: `x-custom-field`
   - Example: `x-internal-id`
   - Example: `x-validation-level`

2. Enter a value in the "Value (JSON)" field
   - Can be a simple string: `"my-value"`
   - Can be a number: `42`
   - Can be a boolean: `true` or `false`
   - Can be an object: `{"category": "important", "level": 5}`
   - Can be an array: `["tag1", "tag2", "tag3"]`

3. Click "Add" button

### Step 4: Save the Property
- Click "Save" to persist your changes
- Extensions will be included in the property schema

## Rules and Validation

### Key Requirements
- ✅ Must start with `x-`
- ✅ Can contain letters (a-z, A-Z)
- ✅ Can contain numbers (0-9)
- ✅ Can contain hyphens (-) and underscores (_)
- ❌ Cannot contain spaces or special characters
- ❌ Cannot be duplicate within the same property

### Value Format
- Can be any valid JSON value
- Plain text is accepted (will be treated as a string)
- Complex JSON structures are fully supported

## Examples

### Example 1: Simple String Extension
```
Key: x-display-name
Value: "User Email Address"
```

### Example 2: Numeric Extension
```
Key: x-priority
Value: 10
```

### Example 3: Boolean Flag
```
Key: x-searchable
Value: true
```

### Example 4: Complex Object
```
Key: x-validation
Value: {
  "strategy": "strict",
  "errorMessage": "Invalid format",
  "retries": 3
}
```

### Example 5: Array of Values
```
Key: x-tags
Value: ["user-input", "required", "pii"]
```

## Common Use Cases

### 1. Documentation Metadata
```
x-display-label: "Customer Phone Number"
x-help-text: "Enter phone number in international format"
x-example-value: "+1-555-123-4567"
```

### 2. UI Hints
```
x-widget: "color-picker"
x-placeholder: "Select a color..."
x-icon: "palette"
```

### 3. Validation Rules
```
x-validation-level: "strict"
x-custom-validator: "emailValidator"
x-error-message: "Please enter a valid email address"
```

### 4. Internal Tracking
```
x-internal-id: 12345
x-created-by: "data-team"
x-version: "2.1.0"
```

### 5. Feature Flags
```
x-deprecated-in: "v2.0.0"
x-experimental: true
x-beta-feature: false
```

### 6. Business Logic
```
x-pricing-tier: "premium"
x-access-level: "admin-only"
x-data-classification: "confidential"
```

## How Extensions Appear in OpenAPI Output

Extensions are merged directly into the property schema:

```yaml
properties:
  email:
    type: string
    format: email
    description: User's email address
    x-display-name: "Email Address"
    x-searchable: true
    x-validation:
      strategy: strict
      errorMessage: "Invalid email format"
```

## Managing Extensions

### View Extensions
- Open the property editor
- Scroll to the Extensions section
- All extensions are listed with their keys and values

### Edit an Extension
- Remove the existing extension
- Add it again with the new value

### Remove an Extension
- Click the delete icon (🗑️) next to the extension in the list

### Clear All Extensions
- Remove each extension individually
- Save the property

## Tips and Best Practices

1. **Use Descriptive Names**: Choose clear, meaningful extension names
   - ✅ `x-ui-component-type`
   - ❌ `x-t`

2. **Follow Naming Conventions**: Use kebab-case for multi-word extensions
   - ✅ `x-error-message`
   - ❌ `x-ErrorMessage` or `x-error_message`

3. **Document Your Extensions**: Keep a record of what each custom extension means in your organization

4. **Use Consistent Prefixes**: For organization-specific extensions, consider using a namespace
   - `x-acme-internal-id`
   - `x-acme-classification`

5. **Validate JSON**: For complex values, validate your JSON before adding
   - Use a JSON validator online if unsure

6. **Don't Overuse**: Only add extensions when standard OpenAPI properties don't suffice

## Troubleshooting

### "Extension keys must start with 'x-'"
- Make sure your key begins with the lowercase letters `x-`
- Example: Change `custom-field` to `x-custom-field`

### "This extension key already exists"
- You cannot have duplicate keys
- Remove the existing extension first, or choose a different key name

### "Extension keys can only contain..."
- Remove any special characters or spaces
- Use only: letters, numbers, hyphens, and underscores
- Example: Change `x-my field!` to `x-my-field`

### Value Not Saving Correctly
- Make sure your value is valid JSON
- Strings should be in quotes: `"my-string"`
- Objects need curly braces: `{"key": "value"}`
- Arrays need square brackets: `["item1", "item2"]`

## Related Documentation
- [OpenAPI 3.1 Specification - Extension Properties](https://spec.openapis.org/oas/v3.1.0#specification-extensions)
- [Property Extensions Feature Documentation](./PROPERTY_EXTENSIONS_FEATURE.md)

