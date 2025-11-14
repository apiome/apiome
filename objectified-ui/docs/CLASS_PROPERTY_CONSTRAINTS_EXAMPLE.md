# Class Property Constraints - Visual Example

## Dialog Structure

```
┌─────────────────────────────────────────────────────────────┐
│ Edit Property in Class                                    × │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│ ℹ️ When editing a property that is a member of a class,    │
│    only the name and constraints can be modified. The      │
│    type and base type are read-only.                       │
│                                                             │
│ ╔═══════════════════════════════════════════════════════╗ │
│ ║ Property Type (Read-Only)                             ║ │
│ ║ [string[]] (References another class)                 ║ │
│ ╚═══════════════════════════════════════════════════════╝ │
│                                                             │
│ Property Name: [email                                    ] │
│                                                             │
│ Description:                                                │
│ ┌─────────────────────────────────────────────────────┐   │
│ │ User's email address                                │   │
│ └─────────────────────────────────────────────────────┘   │
│                                                             │
│ OpenAPI 3.1.0 Extensions                                   │
│ ☑ Required - Must be present in the object                │
│ ☐ Deprecated - Should be transitioned out of usage        │
│ ☐ Read Only - Only in responses (OpenAPI)                 │
│ ☐ Write Only - Only in requests (OpenAPI)                 │
│                                                             │
│ ───────────────────────────────────────────────────────── │
│ Constraints                                                 │
│                                                             │
│ String Constraints                                          │
│ Min Length: [5        ]  Max Length: [100     ]           │
│                                                             │
│ Pattern (Regex):                                            │
│ [^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$       ] │
│ Regular expression pattern for validation                   │
│                                                             │
│ Format:                                                     │
│ [email                                                   ] │
│ e.g., date, date-time, email, uri, uuid                    │
│                                                             │
│ Enum Values                                                 │
│ Add enum value: [                               ] [+]      │
│                                                             │
│ Default Value:                                              │
│ [user@example.com                                        ] │
│ Default value (JSON format for objects/arrays)             │
│                                                             │
│ Example Value:                                              │
│ ┌─────────────────────────────────────────────────────┐   │
│ │ "john.doe@example.com"                              │   │
│ └─────────────────────────────────────────────────────┘   │
│ Example value (JSON format)                                │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│                                         [Cancel]  [Save]    │
└─────────────────────────────────────────────────────────────┘
```

## Example 1: String Property with Constraints

**Property Type:** `string`

**Available Constraints:**
- Min Length: 1
- Max Length: 255
- Pattern: `^[A-Za-z0-9_]+$`
- Format: `email`, `uri`, `date-time`, etc.
- Enum: List of allowed values
- Default: `"default value"`

## Example 2: Number Property with Constraints

**Property Type:** `number`

```
Constraints

Number Constraints
Minimum: [0        ]  Maximum: [100      ]
☐ Exclusive           ☑ Exclusive

Multiple Of:
[0.01                                                    ]
Value must be a multiple of this number

Default Value:
[50                                                      ]
```

**Available Constraints:**
- Minimum: 0 (with exclusive option)
- Maximum: 100 (with exclusive option)
- Multiple Of: 0.01 (for decimal precision)
- Default: 50

## Example 3: Array Property with Constraints

**Property Type:** `string[]`

```
Constraints

String Constraints (for items)
Min Length: [1        ]  Max Length: [50       ]

Array Constraints
Min Items: [1        ]  Max Items: [10       ]
☑ Unique Items (all items must be unique)

Default Value:
[["item1", "item2"]                                      ]
```

**Available Constraints:**
- Item constraints (based on item type)
- Min Items: 1
- Max Items: 10
- Unique Items: true
- Default: `["item1", "item2"]`

## Example 4: Enum Property

**Property Type:** `string`

```
Constraints

Enum Values
Add enum value: [                               ] [+]

┌──────────────────────────────────────────────────────┐
│ ● active                                         [🗑] │
│ ● inactive                                       [🗑] │
│ ● pending                                        [🗑] │
│ ● suspended                                      [🗑] │
└──────────────────────────────────────────────────────┘

Default Value:
["active"                                                ]
```

## Example 5: Object Property with Additional Properties

**Property Type:** `object`

```
Object Schema Settings

Additional Properties
○ Default - Use JSON Schema default (allows additional properties)
● Allow Additional - Explicitly allow any additional properties
○ Strict Schema - Only defined properties allowed (additionalProperties: false)
```

## Use Cases

### Use Case 1: Email Address Validation
```yaml
Property: email
Type: string (read-only)
Constraints:
  - Format: email
  - Min Length: 5
  - Max Length: 255
  - Required: true
  - Default: ""
```

### Use Case 2: Age Range Validation
```yaml
Property: age
Type: integer (read-only)
Constraints:
  - Minimum: 0
  - Maximum: 150
  - Required: true
```

### Use Case 3: Status Enum
```yaml
Property: status
Type: string (read-only)
Constraints:
  - Enum: ["active", "inactive", "pending"]
  - Default: "active"
  - Required: true
```

### Use Case 4: Tag Array
```yaml
Property: tags
Type: string[] (read-only)
Item Constraints:
  - Min Length: 1
  - Max Length: 50
Array Constraints:
  - Min Items: 1
  - Max Items: 10
  - Unique Items: true
```

## Benefits

1. **Type Safety**: Type is read-only, preventing accidental type changes
2. **Constraint Validation**: All JSON Schema constraints are available
3. **Clear UI**: Constraints are grouped by category
4. **Context-Aware**: Only relevant constraints are shown
5. **Easy to Use**: Intuitive form fields with helpful descriptions
6. **Standards-Based**: Follows JSON Schema and OpenAPI specifications

