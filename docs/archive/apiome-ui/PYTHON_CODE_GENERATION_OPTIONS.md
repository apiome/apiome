# Python Code Generation Options - Feature Addition

## Date
December 10, 2025

## Overview
Added comprehensive Python code generation options to the Feature Roadmap, expanding beyond the currently implemented Pydantic models to include dataclasses and SQLAlchemy models.

## Changes Made

### 1. Updated Schema-to-Code Section
**File:** `FEATURE_ROADMAP.md` (Lines ~580-615)

**Changes:**
- Broke out Python generation into separate options:
  - ✅ **Python - Pydantic**: Already implemented
  - **Python - Dataclasses**: New option with detailed features
  - **Python - SQLAlchemy**: New option with ORM capabilities
  - **Python - Mixed**: Hybrid approach combining multiple styles

**Dataclasses Features Added:**
- Standard library dataclasses (Python 3.7+)
- Optional field defaults and factories
- JSON serialization/deserialization support
- Immutable (frozen) option
- Post-init validation hooks
- Inheritance and composition support

**SQLAlchemy Features Added:**
- SQLAlchemy 2.0+ declarative models
- Automatic table name generation
- Primary key and foreign key constraints
- Relationship mappings (one-to-many, many-to-many)
- Column types from OpenAPI formats
- Indexes and unique constraints
- Alembic migration generation support
- Optional type hints for mypy compatibility

### 2. Added Python Code Generation Options Section
**File:** `FEATURE_ROADMAP.md` (Lines ~620-720)

Created a detailed new section with:

**Pydantic Models (Current)** - Already implemented
- Full OpenAPI constraint validation
- JSON schema compliance
- Field validators and root validators
- Computed fields and properties
- Example code showing best practices

**Dataclasses** - To be implemented
- Lightweight, standard library approach
- No external dependencies
- Configuration options (frozen, defaults, slots)
- Example code with post-init validation

**SQLAlchemy Models** - To be implemented
- Database-first ORM approach
- Automatic relationship mapping
- Migration support via Alembic
- Configuration options (table names, indexes, cascades)
- Example code with modern SQLAlchemy 2.0 syntax

**Hybrid Models (Pydantic + SQLAlchemy)** - To be implemented
- Best of both worlds approach
- Database persistence + validation
- Example showing separation of concerns

**Generation Settings**
- Choose model type per schema/class
- Bulk generation with consistent style
- Include type stubs (.pyi files)
- Generate unit tests
- Create requirements.txt/pyproject.toml
- Add mypy/pylint configuration

### 3. Updated Export Section
**File:** `FEATURE_ROADMAP.md` (Line ~1156)

**Changed:**
- From: `- Python models`
- To: `- Python models (Pydantic, Dataclasses, SQLAlchemy)`

This makes it clear that multiple Python model types are supported.

## Implementation Considerations

### Dataclasses Generation

**Pros:**
- No external dependencies (standard library)
- Lightweight and fast
- Good IDE support with type hints
- Familiar to Python developers

**Cons:**
- No built-in validation
- Manual JSON serialization needed
- Less feature-rich than Pydantic

**Use Cases:**
- Internal data structures
- Performance-critical applications
- Projects avoiding external dependencies
- Simple DTOs without complex validation

**Implementation Notes:**
- Use `@dataclass` decorator with configurable parameters
- Generate `__post_init__` for basic validation
- Optional: Include `dacite` or `marshmallow` for JSON handling
- Support `@dataclass(frozen=True)` for immutable objects
- Generate type hints for all fields

### SQLAlchemy Models Generation

**Pros:**
- Direct database mapping
- Powerful ORM features
- Migration support (Alembic)
- Industry standard for Python ORMs

**Cons:**
- Requires database knowledge
- More complex than plain models
- Runtime overhead of ORM

**Use Cases:**
- Database-backed applications
- Full-stack applications
- Projects using PostgreSQL, MySQL, etc.
- When you need relationships and transactions

**Implementation Notes:**
- Use SQLAlchemy 2.0+ modern declarative syntax
- Use `Mapped[]` type hints for better type checking
- Generate relationships from OpenAPI `$ref` connections
- Auto-generate Alembic migrations from schema changes
- Support for:
  - Primary keys (from `id` fields or explicit markers)
  - Foreign keys (from relationships in canvas)
  - Indexes (from performance hints or explicit markers)
  - Unique constraints (from schema constraints)
  - Check constraints (from min/max, enum values)

### Hybrid Models

**Approach:**
- Generate both SQLAlchemy (for DB) and Pydantic (for API) models
- Use Pydantic's `model_config = ConfigDict(from_attributes=True)`
- Allows conversion: `User.model_validate(user_db)`
- Keeps concerns separated (persistence vs. validation)

**Example Workflow:**
1. OpenAPI schema → SQLAlchemy model (DB layer)
2. OpenAPI schema → Pydantic model (API layer)
3. Controller converts between them

## Technical Requirements

### Dependencies to Consider

**Pydantic** (already used):
```
pydantic>=2.0
```

**Dataclasses** (standard library):
- No dependencies for basic generation
- Optional: `dacite` or `dataclasses-json` for serialization

**SQLAlchemy**:
```
sqlalchemy>=2.0
alembic>=1.12  # for migrations
```

**Type Checking**:
```
mypy>=1.0
sqlalchemy[mypy]
```

## UI/UX Design

### Code Generation Dialog

**Model Type Selector:**
- Radio buttons or dropdown:
  - [ ] Pydantic (recommended for APIs)
  - [ ] Dataclasses (lightweight, no deps)
  - [ ] SQLAlchemy (database models)
  - [ ] Hybrid (Pydantic + SQLAlchemy)

**Options Panel (context-sensitive):**

*For Dataclasses:*
- [ ] Frozen (immutable)
- [ ] Include slots
- [ ] Add post-init validation
- [ ] Generate JSON helpers
- [ ] Include type stubs

*For SQLAlchemy:*
- [ ] Generate Alembic migrations
- [ ] Include relationships
- [ ] Custom table names
- [ ] Add indexes
- Database type: [PostgreSQL ▼]

*For Hybrid:*
- All of the above, split between models

**Preview Window:**
- Split view showing both files (for hybrid)
- Syntax highlighting
- Copy to clipboard button

## Testing Strategy

### Unit Tests to Generate

**Dataclasses:**
- Test instantiation
- Test immutability (if frozen)
- Test JSON serialization/deserialization
- Test validation in `__post_init__`

**SQLAlchemy:**
- Test model creation
- Test relationships
- Test constraints
- Migration test (up/down)

**Hybrid:**
- Test SQLAlchemy model
- Test Pydantic model
- Test conversion between them

## Future Enhancements

1. **Advanced Relationship Handling**
   - Detect many-to-many relationships
   - Generate association tables
   - Handle circular references

2. **Migration Management**
   - Visual diff of schema changes
   - One-click migration generation
   - Migration history tracking

3. **Performance Optimization**
   - Lazy loading configuration
   - Eager loading hints
   - Query optimization suggestions

4. **Database-Specific Features**
   - PostgreSQL: JSONB, Arrays, Custom types
   - MySQL: Full-text search
   - SQLite: Simplified models

5. **FastAPI Integration**
   - Generate FastAPI routers
   - CRUD endpoints from models
   - OpenAPI spec re-import

## Documentation Needs

- User guide for each model type
- When to use which approach
- Example projects for each style
- Migration guide (converting between types)
- Best practices guide

## Priority Recommendation

**High Priority:**
1. SQLAlchemy models - Very commonly requested
2. Hybrid models - Best for full-stack apps

**Medium Priority:**
3. Dataclasses - Nice for lightweight use cases

**Lower Priority:**
4. Advanced features (migrations UI, etc.)

## Success Metrics

- Number of users generating Python code
- Model type distribution (which are most popular)
- User feedback on generated code quality
- Issue reports about generated code
- Feature requests for Python-specific options

## Status

**Current:** Feature documented in roadmap
**Next Steps:** 
1. Design UI for model type selection
2. Implement dataclasses generator
3. Implement SQLAlchemy generator
4. Implement hybrid generator
5. Add unit tests for generators
6. Update documentation
7. Beta test with users

---

**Last Updated:** December 10, 2025
**Author:** Feature Roadmap Update
**Status:** ✅ Documented in Roadmap, awaiting implementation

