# Scala Case Class Generation Feature

## Overview

Added **Scala Case Class Generation** to the Studio Generate tab. Users can now generate Scala case classes from their Apiome schema classes with support for Play JSON, Circe, or no codec library.

**Date**: December 9, 2024

---

## Features Implemented

### Scala Code Generation

Generates complete Scala code with:

✅ **Case Classes** - Immutable data structures  
✅ **Option Types** - For nullable/optional fields  
✅ **Sealed Traits** - For enumerations  
✅ **Companion Objects** - With JSON codec instances  
✅ **Play JSON Format** - Implicit Format instances  
✅ **Circe Codecs** - Implicit Encoder/Decoder instances  
✅ **ScalaDoc Comments** - From class/property descriptions  
✅ **Package Declarations** - Proper package structure  
✅ **Type Imports** - java.time.Instant, java.util.UUID  
✅ **Proper Naming** - PascalCase types, camelCase fields  

### Codec Library Support

| Library | Format | Use Case |
|---------|--------|----------|
| **Play JSON** | `implicit val format: Format[T]` | Play Framework applications |
| **Circe** | `implicit val encoder/decoder` | Pure functional Scala apps |
| **None** | No codecs | Plain case classes only |

### Type Mapping

| JSON Schema Type | Scala Type |
|-----------------|------------|
| string | String |
| string (format: date/date-time) | java.time.Instant |
| string (format: uuid) | java.util.UUID |
| integer | Int |
| number | Double |
| boolean | Boolean |
| array | List[Type] |
| object | Map[String, Any] |
| $ref | Referenced Type |
| enum | Sealed Trait |
| nullable/optional | Option[Type] |

---

## Usage

### In Studio Generate Tab

1. Navigate to any project/version with classes
2. Click the **Generate** tab
3. Select **Scala** from the language dropdown
4. Select codec library from the dropdown:
   - **Play JSON** - For Play Framework apps
   - **Circe** - For pure functional Scala
   - **No Codec** - Plain case classes only
5. View the generated Scala code in Monaco Editor
6. Click **Copy** to copy to clipboard
7. Click **Export** to download as `Models.scala`

---

## Example Output

### With Play JSON

```scala
/**
 * Scala Case Classes Generated from Apiome
 * Project: MyAPI
 * Version: 1.0
 * Generated: 2024-12-09T...
 */

package com.example.models

import play.api.libs.json._
import java.time.Instant
import java.util.UUID

// Enumerations
sealed trait UserStatus
object UserStatus {
  case object Active extends UserStatus
  case object Inactive extends UserStatus
  case object Suspended extends UserStatus

  val values: Set[UserStatus] = Set(Active, Inactive, Suspended)

  def fromString(s: String): Option[UserStatus] = s match {
    case "active" => Some(Active)
    case "inactive" => Some(Inactive)
    case "suspended" => Some(Suspended)
    case _ => None
  }
}

// Case Classes
/**
 * User account information
 */
case class User(
  /** User's full name */
  name: String,
  email: String,
  age: Option[Int],
  status: UserStatus,
  createdAt: Option[Instant]
)

object User {
  implicit val userFormat: Format[User] = Json.format[User]
}

case class Post(
  title: String,
  content: Option[String],
  author: User,
  publishedAt: Option[Instant]
)

object Post {
  implicit val postFormat: Format[Post] = Json.format[Post]
}
```

### With Circe

```scala
package com.example.models

import io.circe._
import io.circe.generic.semiauto._
import java.time.Instant
import java.util.UUID

// Case Classes
case class User(
  name: String,
  email: String,
  age: Option[Int],
  status: String,
  createdAt: Option[Instant]
)

object User {
  implicit val userEncoder: Encoder[User] = deriveEncoder[User]
  implicit val userDecoder: Decoder[User] = deriveDecoder[User]
}
```

### No Codec (Plain)

```scala
package com.example.models

import java.time.Instant
import java.util.UUID

// Case Classes
case class User(
  name: String,
  email: String,
  age: Option[Int],
  status: String,
  createdAt: Option[Instant]
)

case class Post(
  title: String,
  content: Option[String],
  author: User,
  publishedAt: Option[Instant]
)
```

---

## Technical Implementation

### Files Created

**`src/app/utils/scala-generator.ts`** (350+ lines)
- `mapTypeToScala()` - Maps JSON Schema types to Scala types
- `toPascalCase()` - Converts names to PascalCase for types
- `toCamelCase()` - Converts names to camelCase for fields
- `generateEnum()` - Generates sealed trait enumerations
- `generateCaseClass()` - Generates case class definitions
- `generatePlayJsonFormat()` - Generates Play JSON codecs
- `generateCirceCodec()` - Generates Circe codecs
- `generateImports()` - Generates import statements
- `generateScala()` - Main export function

### Files Modified

**`src/app/ade/studio/page.tsx`**

1. **State Variables** (Line ~119-120)
   ```typescript
   const [generatedScalaCode, setGeneratedScalaCode] = useState<string>('');
   const [generateLanguage, setGenerateLanguage] = useState<'python' | 'typescript' | 'sql' | 'graphql' | 'scala'>('python');
   const [scalaCodecLibrary, setScalaCodecLibrary] = useState<'play-json' | 'circe' | 'none'>('play-json');
   ```

2. **Imports** (Line ~20)
   ```typescript
   import { generateScala } from '../../utils/scala-generator';
   ```

3. **Initial Generation** (Line ~330)
   - Generates Scala when classes load
   - Caches in `generatedScalaCode` state

4. **Language Change Effect** (Line ~1755)
   - Switches to Scala code when language changes
   - Includes `generatedScalaCode` in dependencies

5. **Scala Codec Library Effect** (Line ~1810)
   - Regenerates Scala when codec library changes
   - Similar to SQL dialect effect

6. **View Mode Effect** (Line ~1710)
   - Regenerates Scala when switching to Generate tab

7. **UI Updates** (Line ~2520-2570)
   - Added "Scala" option to language selector
   - Added codec library selector (Play JSON / Circe / None)
   - Updated header to show "Generated Scala - {Codec}"
   - Updated subtitle with Scala description
   - Added `.scala` file extension for export
   - Added `scala` language to Monaco Editor
   - Added Scala placeholder text

**`public/WHATS_NEW.md`**
- Added Scala to the Generate tab features list

---

## Features

### Naming Conventions

- **Case Classes**: Exact database names (preserves original casing)
- **Fields**: Exact database names (preserves original casing)
- **Enums**: Exact enum values (preserves original casing)
- **Packages**: Lowercase with dots (com.example.models)

**Note**: Scala generator preserves the exact naming from your database schema, ensuring consistency across your entire stack.

### Special Handling

**Enumerations**:
- Property enum values → Sealed trait with case objects
- Enum name: `{ClassName}{PropertyName}` (UserStatus, PostCategory)
- Includes `fromString` helper method
- Includes `values` set with all options

**Optional Fields**:
- Non-required fields wrapped in `Option[Type]`
- Uses JSON Schema `required` array
- Checks both schema and property-level required flags

**Arrays**:
- `List[Type]` for all array types
- Optional arrays: `Option[List[Type]]`
- Required arrays: `List[Type]`

**References**:
- `$ref` properties become type references
- Foreign key relationships preserved
- Circular references supported

**Descriptions**:
- ScalaDoc format (`/** ... */`)
- Multi-line descriptions supported
- Extracted from class and property descriptions

---

## API

### generateScala Function

```typescript
export function generateScala(
  classes: any[],
  codecLibrary: 'play-json' | 'circe' | 'none' = 'play-json',
  options?: {
    projectName?: string;
    version?: string;
    description?: string;
    packageName?: string;
    includeCompanionObjects?: boolean;
  }
): string
```

**Parameters**:
- `classes` - Array of class objects with properties
- `codecLibrary` - Codec library to use (default: 'play-json')
- `options.projectName` - Project name for header
- `options.version` - Version for header
- `options.description` - Description for header
- `options.packageName` - Package name (default: 'com.example.models')
- `options.includeCompanionObjects` - Generate companion objects (default: true)

**Returns**: Scala code as string

---

## Testing

### Manual Testing Steps

1. ✅ Create classes with various property types
2. ✅ Switch to Generate tab
3. ✅ Select Scala from dropdown
4. ✅ Verify Scala code displays with Play JSON (default)
5. ✅ Change to Circe codec
6. ✅ Verify Circe codecs are generated
7. ✅ Change to No Codec
8. ✅ Verify plain case classes without codecs
9. ✅ Check case class definitions are correct
10. ✅ Check Option types for optional fields
11. ✅ Check sealed traits for enums
12. ✅ Check ScalaDoc comments
13. ✅ Copy to clipboard works
14. ✅ Export downloads `Models.scala`
15. ✅ Monaco Editor shows Scala syntax highlighting
16. ✅ Switch to other languages and back works

---

## Benefits

✅ **Type Safety** - Immutable case classes with strong typing  
✅ **Functional** - Pure functional data structures  
✅ **JSON Support** - Play JSON or Circe codecs included  
✅ **Enums** - Sealed traits for exhaustive pattern matching  
✅ **Optional Fields** - Explicit Option types  
✅ **Documentation** - ScalaDoc comments preserved  
✅ **Industry Standard** - Idiomatic Scala code  
✅ **Copy/Export** - Easy clipboard copy and file download  

---

## Comparison with Other Languages

| Feature | Python | TypeScript | GraphQL | SQL | Scala |
|---------|--------|------------|---------|-----|-------|
| **Purpose** | DTOs | DTOs | API Schema | Database | DTOs |
| **Immutability** | ❌ | ❌ | N/A | N/A | ✅ |
| **Type Safety** | ✅ | ✅ | ✅ | ✅ | ✅ |
| **Nullable** | Optional | undefined/null | null | NULL | Option |
| **Enums** | Literal | Union | Enum | CHECK | Sealed Trait |
| **JSON Codecs** | ✅ | ❌ | N/A | N/A | ✅ |
| **Validation** | ✅ | ❌ | ✅ | ✅ | ❌ |

---

## Future Enhancements

### Near-Term
- [ ] Validation with refined types
- [ ] Smart constructors
- [ ] Value classes for type safety
- [ ] Newtype wrappers
- [ ] Custom JSON codecs for special types

### Mid-Term
- [ ] Akka HTTP routes generation
- [ ] http4s endpoints generation
- [ ] Slick table definitions
- [ ] Doobie queries
- [ ] ZIO schema generation

### Long-Term
- [ ] ScalaTest test generators
- [ ] ScalaCheck generators
- [ ] Tapir endpoint definitions
- [ ] gRPC service definitions
- [ ] Scala 3 enum types

---

## Known Limitations

1. **Nested Objects**: Serialized as `Map[String, Any]` (no nested case classes yet)
2. **Validation**: No built-in validation (consider adding refined types)
3. **oneOf/anyOf**: Not converted to sealed traits (uses base types)
4. **allOf**: Not converted to trait hierarchies (uses merged type)
5. **Custom Codecs**: Only auto-derived codecs (no custom encoding)
6. **Date Formats**: Uses `java.time.Instant` (may need custom formats)

---

## Conclusion

Scala case class generation is **fully implemented and functional**. Users can now generate idiomatic, type-safe Scala code from their Apiome models with support for Play JSON, Circe, or plain case classes.

**Status**: ✅ **COMPLETE AND READY TO USE**

---

**Implementation Date**: December 9, 2024  
**Files**: 1 created, 2 modified  
**Lines of Code**: ~400 lines

