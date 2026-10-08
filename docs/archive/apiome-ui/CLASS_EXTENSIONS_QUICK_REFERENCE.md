# Class Extensions Quick Reference

## What are Extensions?

Extensions are custom properties you can add to your class definitions that start with `x-`. They follow the OpenAPI 3.1 specification and allow you to add metadata that tools, documentation generators, and other systems can use.

## How to Add Extensions

1. **Open Class Editor**
   - Create a new class or edit an existing one
   - Scroll to the bottom of the form

2. **Find Extensions Section**
   - Look for the "Extensions" section (gray background box)
   - It's located after the "Deprecated" section

3. **Add an Extension**
   - **Key field**: Enter a name starting with `x-` (e.g., `x-team-owner`)
   - **Value field**: Enter a JSON value (e.g., `"platform-team"`)
   - Click **Add** button or press Enter

4. **Save the Class**
   - Click Save to persist your extensions

## Extension Key Rules

✅ **Valid Keys:**
- Must start with `x-`
- Can contain: letters, numbers, hyphens, underscores
- Examples: `x-internal-id`, `x-team-owner`, `x-version-2`

❌ **Invalid Keys:**
- Missing `x-` prefix: `internal-id`
- Spaces: `x-my key`
- Special characters: `x-key@value`, `x-key$`

## Extension Value Types

Extensions support any valid JSON value:

### String
```
Key: x-team-owner
Value: "platform-team"
or: platform-team (quotes optional for simple strings)
```

### Number
```
Key: x-api-version
Value: 2
or: 3.14
```

### Boolean
```
Key: x-deprecated
Value: true
or: false
```

### Object
```
Key: x-metadata
Value: {"team": "platform", "status": "active"}
```

### Array
```
Key: x-tags
Value: ["core", "v2", "stable"]
```

### Null
```
Key: x-placeholder
Value: null
```

## Common Use Cases

### Internal Tracking
```
x-internal-id: "CLASS-001"
x-jira-ticket: "PROJ-1234"
x-created-by: "user@example.com"
```

### Team Organization
```
x-team-owner: "platform-team"
x-domain: "user-management"
x-status: "stable"
```

### Code Generation
```
x-codegen-package: "com.example.models"
x-codegen-generate-builder: true
x-codegen-imports: ["java.time.Instant"]
```

### Documentation
```
x-examples-url: "https://docs.example.com/models/user"
x-migration-guide: "https://wiki.example.com/migrate-user-v2"
```

### API Gateway Integration
```
x-amazon-apigateway-integration: {"type": "aws_proxy"}
x-rate-limit: 1000
```

## Tips

### Organizing Extensions
- Use consistent naming: `x-yourcompany-property`
- Group related extensions with prefixes: `x-aws-*`, `x-codegen-*`
- Document your custom extensions in your team wiki

### Value Format
- For simple text, quotes are optional: `platform-team` or `"platform-team"`
- For complex data, use valid JSON: `{"key": "value"}`
- Numbers don't need quotes: `42` or `3.14`
- Booleans: `true` or `false` (no quotes)

### Best Practices
- Keep extension keys descriptive but concise
- Use lowercase with hyphens: `x-team-owner` not `x-TeamOwner`
- Document what each extension means for your team
- Be consistent across similar classes

## Viewing Extensions

Extensions appear in:
- ✅ JSON view (class dialog)
- ✅ YAML view (class dialog)
- ✅ OpenAPI export
- ✅ Class schema in database

## Editing/Removing Extensions

**To Edit:**
1. Remove the old extension (click trash icon)
2. Add it again with the new value

**To Remove:**
1. Click the trash/delete icon next to the extension
2. Save the class

## Examples

### Simple Extension
```
Key: x-internal-id
Value: USER-CLASS-001
```

### Complex Metadata
```
Key: x-metadata
Value: {
  "owner": "platform-team",
  "created": "2025-01-15",
  "status": "stable",
  "tags": ["core", "v2"]
}
```

### API Gateway Config
```
Key: x-amazon-apigateway-integration
Value: {
  "type": "aws_proxy",
  "httpMethod": "POST",
  "uri": "arn:aws:apigateway:..."
}
```

## Troubleshooting

**"Extension keys must start with x-"**
- Make sure your key starts with lowercase `x-` followed by a hyphen

**"This extension key already exists"**
- Each key can only be used once per class
- Remove the existing one first if you want to change it

**"Value cannot be empty"**
- Enter a value in the Value field
- Use `null` if you need an explicit null value

**Extension not appearing in OpenAPI output?**
- Make sure you saved the class after adding the extension
- Reload the class editor to verify it was saved

## Need Help?

- See full documentation: `/docs/CLASS_EXTENSIONS_FEATURE.md`
- OpenAPI Spec: https://spec.openapis.org/oas/v3.1.0#specification-extensions
- Ask your team lead about custom extensions your organization uses

