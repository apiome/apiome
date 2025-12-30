# Code Generator Roadmap

### Code Generation

**Python Code Generation Options**

*Pydantic Models (Current)*
- Full OpenAPI constraint validation
- JSON schema compliance
- Field validators and root validators
- Computed fields and properties
- Example output:
  ```python
  from pydantic import BaseModel, Field, field_validator
  from typing import Optional
  
  class User(BaseModel):
      id: int = Field(..., description="User ID")
      name: str = Field(..., min_length=1, max_length=100)
      email: Optional[str] = Field(None, pattern=r'^[\w\.-]+@[\w\.-]+\.\w+$')
      
      @field_validator('email')
      def validate_email(cls, v):
          # Custom validation logic
          return v
  ```

*Dataclasses*
- Lightweight, standard library approach
- No external dependencies
- Type hints for IDE support
- Optional JSON serialization helpers
- Configuration options:
  - Frozen (immutable) classes
  - Field defaults and factories
  - Slots for memory optimization
  - Post-init validation
- Example output:
  ```python
  from dataclasses import dataclass, field
  from typing import Optional
  
  @dataclass(frozen=True)
  class User:
      id: int
      name: str
      email: Optional[str] = None
      
      def __post_init__(self):
          if self.name and len(self.name) > 100:
              raise ValueError("Name too long")
  ```

*SQLAlchemy Models*
- Database-first ORM approach
- Automatic relationship mapping
- Migration support via Alembic
- Configuration options:
  - Table names (auto-generated or custom)
  - Index creation
  - Cascade rules
  - Lazy loading strategies
- Example output:
  ```python
  from sqlalchemy import Column, Integer, String, ForeignKey
  from sqlalchemy.orm import DeclarativeBase, relationship, Mapped, mapped_column
  
  class Base(DeclarativeBase):
      pass
  
  class User(Base):
      __tablename__ = 'users'
      
      id: Mapped[int] = mapped_column(primary_key=True)
      name: Mapped[str] = mapped_column(String(100), nullable=False)
      email: Mapped[str | None] = mapped_column(String(255))
      
      posts: Mapped[list["Post"]] = relationship(back_populates="author")
  ```

*Hybrid Models (Pydantic + SQLAlchemy)*
- Best of both worlds
- Database persistence + validation
- Use Pydantic for API, SQLAlchemy for DB
- Example output:
  ```python
  from sqlalchemy.orm import DeclarativeBase, Mapped
  from pydantic import BaseModel, ConfigDict
  
  # SQLAlchemy Model
  class UserDB(Base):
      __tablename__ = 'users'
      id: Mapped[int] = mapped_column(primary_key=True)
      name: Mapped[str]
  
  # Pydantic Model
  class User(BaseModel):
      model_config = ConfigDict(from_attributes=True)
      id: int
      name: str
  ```

*Generation Settings*
- Choose model type per schema/class
- Bulk generation with consistent style
- Include type stubs (.pyi files)
- Generate unit tests
- Create requirements.txt/pyproject.toml
- Add mypy/pylint configuration

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

**OpenAPI Client Generation**
- One-click client SDK generation
- Integrate with OpenAPI Generator
- Support for all major languages
- Download as package/library
- NPM/PyPI/Maven publishing integration

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

#### Schema-to-Code 📋 PLANNED
- Generate code from schemas in multiple languages:
  - 📋 **TypeScript**: Interfaces, types with full composition support
  - 📋 **Python - Pydantic**: Models with validation and constraints
  - 📋 **Python - Dataclasses**: Native Python dataclasses with type hints
    - 📋 Standard library dataclasses (Python 3.7+)
    - 📋 Optional field defaults and factories
    - 📋 JSON serialization/deserialization support
    - 📋 Immutable (frozen) option
    - 📋 Post-init validation hooks
    - 📋 Inheritance and composition support
  - 📋 **Python - SQLAlchemy**: ORM models for database mapping
    - 📋 SQLAlchemy 2.0+ declarative models
    - 📋 Automatic table name generation
    - 📋 Primary key and foreign key constraints
    - 📋 Relationship mappings (one-to-many, many-to-many)
    - 📋 Column types from OpenAPI formats
    - 📋 Indexes and unique constraints
    - 📋 Alembic migration generation support
    - 📋 Optional type hints for mypy compatibility
  - 📋 **Python - Mixed**: Combine multiple approaches
    - 📋 Pydantic + SQLAlchemy hybrid models
    - 📋 Dataclasses with validation decorators
    - 📋 Choose per-class basis
  - 📋 **TypeScript (Extended)**: Zod validators, runtime type checking
  - 📋 **Java**: POJOs, Records, JPA entities
  - 📋 **C#**: Classes, records, EF Core models
  - 📋 **Go**: Structs with JSON tags
  - 📋 **Rust**: Structs with Serde
  - 📋 **Scala**: Case classes with play-json support
  - 📋 **GraphQL**: SDL schema definitions
  - 📋 **SQL**: DDL CREATE TABLE statements (PostgreSQL, MySQL, SQLite, SQL Server, Oracle)
- Customizable generation templates
- 📋 Code generation settings per language:
  - 📋 Naming conventions (camelCase, snake_case, PascalCase)
  - 📋 Nullable vs Optional handling
  - 📋 Validation annotations
  - 📋 Documentation comments
- ✅ Preview generated code before download
- Download as single file or project structure
- Generate with tests/mocks included

| Ticket | Feature Description                       |
|--------|-------------------------------------------|
| #221   | Export to GraphQL SDL                     |
| #222   | Export to AsyncAPI                        |
| #223   | Export to TypeScript                      |
| #224   | Export to Python models                   |
| #225   | Export to Java                            |
| #226   | Export to C#                              |
| #227   | Export to Golang                          |
| #228   | Export to SQL                             |
| #229   | Export to Markdown                        |
| #230   | Export to Excel                           |
| #231   | Export to PDF                             |
| #509   | Add code generation settings per language |

---

# After pathing is completely implemented:

---

### Code Generation for Paths

**API Client Generation** 📋 PLANNED
- **Client SDKs**:
  - TypeScript/JavaScript (axios, fetch)
  - Python (requests, httpx, aiohttp)
  - Java (OkHttp, Retrofit)
  - Go (net/http)
  - C# (HttpClient)
  - Swift (URLSession)
  - Kotlin (Ktor, OkHttp)
- **Client Features**:
  - Type-safe request/response
  - Authentication handling
  - Error handling with typed errors
  - Retry logic and timeouts
  - Request/response interceptors

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

**Server Stub Generation** 📋 PLANNED
- **Server Frameworks**:
  - Node.js (Express, Fastify, Koa, NestJS)
  - Python (FastAPI, Flask, Django REST)
  - Java (Spring Boot, Micronaut, Quarkus)
  - Go (Gin, Echo, Chi)
  - Rust (Actix, Axum)
- **Stub Features**:
  - Route handlers with type hints
  - Request validation middleware
  - Response serialization
  - Error handling patterns
  - OpenAPI validation middleware
- **Stubbing CRUD operations**:
  - Auto-generate CRUD stubs from schemas
  - RESTful endpoint patterns
  - Request/response type safety
  - Mock data generation

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

### CRUD Operation Stubs (NEW)

**Automatic CRUD Generation** 📋 PLANNED
- **One-Click CRUD Creation**:
  - Select schema/class and generate full CRUD operations
  - Generate all 5 operations: Create, Read, Update, Delete, List
  - RESTful URL patterns following best practices
  - Proper HTTP methods and status codes
  - Request/response schemas automatically configured

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

- **CRUD Operation Templates**:
  - **Create (POST /resources)**:
    - Request body: Full schema
    - Response: 201 Created with created resource
    - Validation: Required fields, constraints
    - Error responses: 400 (validation), 409 (conflict)

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

- **Read/Get Single (GET /resources/{id})**:
  - Path parameter: Resource ID
  - Response: 200 OK with resource
  - Error responses: 404 (not found), 403 (forbidden)

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

- **List/Get All (GET /resources)**:
  - Query parameters: pagination (page, limit, offset)
  - Query parameters: filtering, sorting
  - Response: 200 OK with array of resources
  - Pagination metadata in response

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

- **Update (PUT /resources/{id})**:
  - Path parameter: Resource ID
  - Request body: Full schema (replace entire resource)
  - Response: 200 OK with updated resource
  - Error responses: 404 (not found), 400 (validation), 409 (conflict)

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

- **Partial Update (PATCH /resources/{id})**:
  - Path parameter: Resource ID
  - Request body: Partial schema (only changed fields)
  - Response: 200 OK with updated resource
  - Error responses: 404 (not found), 400 (validation)

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

- **Delete (DELETE /resources/{id})**:
  - Path parameter: Resource ID
  - Response: 204 No Content or 200 OK with deleted resource
  - Error responses: 404 (not found), 409 (conflict if dependencies)

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

- **Bulk Operations** (Optional):
  - **Bulk Create (POST /resources/bulk)**
  - **Bulk Update (PUT /resources/bulk)**
  - **Bulk Delete (DELETE /resources/bulk)**

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

**CRUD Customization** 📋 PLANNED
- **URL Pattern Customization**:
  - Choose ID parameter name (id, userId, resourceId, etc.)
  - Choose ID type (integer, UUID, string)
  - Custom path segments (/api/v1/resources, /resources)
  - Singular vs plural resource names
  - Nested resources (/users/{userId}/posts)

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

- **Operation Selection**:
  - Enable/disable specific operations
  - Read-only APIs (GET operations only)
  - Write-only APIs (POST operations only)
  - Custom operation combinations

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

- **Response Customization**:
  - Choose response wrapper format
  - Include/exclude metadata
  - Custom pagination format
  - Custom error response schema
  - HATEOAS links (include navigation links)

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

- **Request Validation**:
  - Auto-generate validation rules from schema
  - Custom validation messages
  - Field-level validation
  - Business rule validation hooks
  - Async validation support

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

**Mock Data Generation** 📋 PLANNED
- **Stub Response Data**:
  - Generate realistic mock data based on schema
  - Faker.js integration for common fields
  - Respect constraints (min/max, patterns, enums)
  - Multiple example variations
  - Configurable data set size

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

- **Mock Data Strategies**:
  - Static examples from schema
  - Dynamic random generation
  - Incremental IDs
  - Timestamp generation
  - Related data consistency (foreign keys)

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

**Server Stub Implementation** 📋 PLANNED
- **Framework-Specific Stubs**:
    - **Express.js (Node.js)**:
      ```javascript
      // GET /users/:id
      router.get('/users/:id', async (req, res) => {
        const { id } = req.params;
        // TODO: Implement database query
        const user = mockData.users.find(u => u.id === id);
        if (!user) return res.status(404).json({ error: 'User not found' });
        res.json(user);
      });
      ```

    - **FastAPI (Python)**:
      ```python
      @app.get("/users/{user_id}", response_model=User)
      async def get_user(user_id: int):
          # TODO: Implement database query
          user = mock_data.get_user(user_id)
          if not user:
              raise HTTPException(status_code=404, detail="User not found")
          return user
      ```

    - **Spring Boot (Java)**:
      ```java
      @GetMapping("/users/{id}")
      public ResponseEntity<User> getUser(@PathVariable Long id) {
          // TODO: Implement database query
          Optional<User> user = mockData.getUserById(id);
          return user.map(ResponseEntity::ok)
                     .orElse(ResponseEntity.notFound().build());
      }
      ```

- **Stub Features**:
  - TODO comments for implementation
  - Mock data pre-populated
  - Request validation enabled
  - Response serialization configured
  - Error handling implemented
  - Logging statements included
  - OpenAPI middleware integrated

---

# Completed
