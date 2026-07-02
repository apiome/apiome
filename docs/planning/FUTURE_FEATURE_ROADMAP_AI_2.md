# AI Planned Feature Roadmap

This outlines the planned features for integrating AI capabilities into Apiome.


### Preparation

- Install Ollama Cluster
- Set up Mac Mini cluster using EXO
- Deploy Ollama with Qwen 2.5 and Llama 3.2 models
- Configure network access and security
- Test Ollama API connectivity from Apiome backend
- Benchmark response times and resource usage
- Establish monitoring and alerting for Ollama cluster health
- Document Ollama setup and maintenance procedures
- Set up networking so that the cluster is only accessible using the 10.1.2.xx subnet
- Set up licensing table to track Ollama usage per tenant
- Set up monitoring of all conversations for auditing purposes
- Set up Guardrails.ai application for guardrails enforcement across the entire platform's AI features

| Ticket | Feature Description              |
|--------|----------------------------------|

### Studio AI Chatbot

**Conversation Features** 📋 PLANNED
- ✅ **Conversation History** (#261):
    - ✅ Persist conversations per project/version
    - ✅ Browse past conversations
    - ✅ Search conversation history
    - ✅ Export conversations as markdown
    - ✅ Clear conversation option
- ✅ **Context Awareness** (#259):
    - ✅ AI knows current project, version, classes
    - ✅ AI can reference existing schemas in responses
    - ✅ AI understands selected items on canvas
    - ✅ AI can see property definitions
    - ✅ Automatic context injection into prompts
- ✅ **Multi-Turn Conversations** (#260):
    - ✅ Follow-up questions with context
    - ✅ Clarification requests
    - ✅ Iterative refinement of schemas
    - ✅ "Make it more like X" type instructions
- Add guardrails to prevent sensitive data exposure
- Add guardrails to prevent malicious code generation

| Ticket | Feature Description                                |
|--------|----------------------------------------------------|
| #262   | Install guardrails.ai server                       |
| #263   | Add guardrails to prevent sensitive data exposure  |
| #264   | Add guardrails to prevent further sensitive issues |

### Ollama Integration

**Ollama API Integration** 📋 PLANNED
- 📋 **Streaming Responses**:
    - ✅ Server-Sent Events (SSE) for streaming (#520)
    - ✅ Token-by-token usage display (#521)
    - ✅ Cancel generation mid-stream (#522)
    - ✅ Progress indication (#523)
- 📋 **Caching**:
    - ✅ Cache common queries (#524)
    - ✅ Semantic similarity matching (#525)
    - ✅ Cache invalidation on schema changes (#526)
- 📋 **Guardrails**:
    - 📋 Prompt filtering for sensitive content
    - 📋 Response filtering for PII
    - 📋 Rate limiting enforcement
    - 📋Logging and audit trails

| Ticket | Feature Description                                 |
|--------|-----------------------------------------------------|
| #527   | Implementation of Guardrails for prompts/responses  |

---

## Complete

**Chatbot Panel** ✅ COMPLETE
- ✅ **Panel Location**:
    - ✅ Slide-out panel from right side of Studio
    - ✅ Floating chat bubble option
    - ✅ Full-screen chat mode for complex conversations
    - ✅ Keyboard shortcut to toggle (`Cmd+Shift+A`)
    - ✅ Bottom right-hand corner of the canvas opens the AI Chatbot
- ✅ **Chat Interface**:
    - ✅ Modern chat UI with message bubbles
    - ✅ User messages vs AI responses clearly distinguished
    - ✅ Typing indicators while AI processes
    - ✅ Markdown rendering in responses
    - ✅ Code blocks with syntax highlighting
    - ✅ Copy button for code snippets
    - ✅ Regenerate response button
    - ✅ Thumbs up/down for feedback
    - ✅ OpenAPI Specifications are parsed using ```json``` markers, click button to view/accept import

**Quick Actions from Chat** 📋 PLANNED
- ✅ AI responses include action buttons (#518):
    - ✅ "Create this class" → One-click class creation
    - ✅ "Add these properties" → Batch property addition
    - ✅ "Apply to current class" → Modify selected class
    - "Generate path for this" → Create CRUD endpoints
    - ✅ "Copy to clipboard" → Copy generated JSON/YAML
- ✅ Preview changes before applying (#519)
- Undo AI-generated changes

**Ollama Connection** 📋 PLANNED
- **Configuration**:
    - Ollama server URL configuration (cluster support)
    - Multiple server endpoints for load balancing
    - Health check and failover
    - Connection timeout settings
    - Retry policies
- **Model Selection**:
    - Choose from available models (queried live from Ollama; includes Qwen 2.5, Llama 3.2, CodeLlama, custom tags when installed):
        - Qwen 2.5
        - Llama 3.2
        - CodeLlama for code-specific tasks
        - Custom fine-tuned models
    - Model switching per task type
    - Model performance comparison
    - ✅ Default model per tenant/project (#266)
- **Resource Management**:
    - GPU memory monitoring
    - Request queuing for high load
    - Priority queues for different users
    - Rate limiting per user/tenant
    - Usage tracking and quotas

### Natural Language to Schema

**Schema Generation from Description** 📋 PLANNED
- 📋 **Input Methods**:
    - ✅ Free-form text description (#267 — Studio AI chat: offline demo + Ollama system prompt)
    - 📋 Structured prompts with templates
    - 📋 Voice input (speech-to-text)
    - 📋 Paste requirements document
- ✅ **Example Prompts** (#268):
    - ✅ "Create a User class with email, password hash, created date, and roles array"
    - ✅ "I need an e-commerce order with line items, shipping address, and payment info"
    - ✅ "Generate a blog post schema with author reference, tags, and comments"
    - ✅ "Create a REST API for managing a todo list application"
- 📋 **Generation Output**:
    - ✅ Preview generated schema before creation (#528)
    - ✅ JSON Schema format display (#529)
    - ✅ Property list with types (#530)
    - ✅ Relationship suggestions (#531)
- ✅ **Iterative Refinement** (#532):
    - ✅ "Add a phone number field"
    - ✅ "Make email required"
    - ✅ "Add validation for password length"
    - ✅ "Include timestamps for audit"

### AI Schema Review & Improvement

**Improvement Suggestions** ✅ (#495 — Studio chat / Ollama system prompt + offline demo)
- ✅ "Consider adding pagination to this list endpoint"
- ✅ "This schema could benefit from inheritance using allOf"
- ✅ "Add a discriminator for this polymorphic type"
- ✅ "Consider breaking this large schema into smaller components"
- ✅ "Add error responses for common failure scenarios"

**Type and Constraint Inference** 📋 PLANNED
- ✅ Suggest type based on property name (#277 — chat refinement + class-skeleton prompt guidance):
    - ✅ `email` → string with email format
    - ✅ `createdAt` → string with date-time format
    - ✅ `age` → integer with minimum 0
    - ✅ `price` → number with minimum 0
    - ✅ `isActive` → boolean
- ✅ Suggest constraints (#278 — chat refinement merges inferred keywords into new properties):
    - ✅ String length limits (`email`, `password`, `description`, …)
    - ✅ Numeric ranges (`age`, `percentage`, `latitude`, …)
    - ✅ Pattern validation (`slug`, `sku`, `phone`, ISO codes, …)
    - ✅ Required vs optional (`id` suggested required when added without an explicit type)

### AI Properties Insights

**Property Creation Suggestions**
- ✅ Common property sets for specific class types
- ✅ Industry-standard property recommendations
- ✅ Context-aware property suggestions based on existing schema
- ✅ Property naming convention analysis

### AI-Powered Property Suggestions

**Smart Property Recommendations** 📋 PLANNED
- ✅ **Trigger Conditions** (#275):
    - ✅ When creating a new class
    - ✅ When class name is entered
    - ✅ On-demand via chat or button
    - ✅ **Analyze** on Add / Edit Property form (#276)
    - ✅ After adding first few properties
- 📋 **Suggestion Types**:
    - 📋 Common properties for class type (e.g., "User" → email, password, name)
    - 📋 Missing standard properties (e.g., id, createdAt, updatedAt)
    - 📋 Related properties based on existing ones
    - 📋 Industry-standard properties (FHIR for healthcare, etc.)
- 📋 **Suggestion UI**:
    - ✅ Property suggestion dropdown (#270)
    - ✅ Bulk accept/reject (#271)
    - ✅ Customize before adding (#272)
    - ✅ "Add all suggested" button (#274)
    - ✅ Explanation for each suggestion (#273)
    - ✅ Trigger conditions for opening the dialog (#275)

### AI Schema Health Insights

**Schema Complexity Analysis** 📋 PLANNED
- ✅ Cognitive complexity score per class (#610)
- ✅ Dependency graph complexity (#611)
- ✅ Cyclomatic complexity for conditional schemas (#612)
- ✅ Maintainability index (#613)
- ✅ Technical debt metrics (#614)

**Actionable Recommendations** 📋 PLANNED
- ✅ **AI-powered suggestions for improvement**
    - ✅ "Add descriptions to 12 classes to improve docs score" (pattern; model uses live metrics)
    - ✅ "Rename 5 properties to follow camelCase convention"
    - ✅ "Split 'User' class - it has 28 properties (recommended max: 15)"
    - ✅ "Add pagination to 'GET /users' endpoint" (optional user focus + metrics)
- ✅ Prioritized action items (quick wins first) (#254)
- ✅ Estimated score impact for each fix (#255)
- ✅ Bulk apply recommendations (#256): structured class/property description fills from the AI dialog

### AI Schema Health Insights

**Best Practice Suggestions** 📋 PLANNED (partially delivered)
- ✅ Context-aware tips from project **domain category** (metadata) and **class-name heuristics** (#615):
    - Authentication-style class names (e.g. RefreshToken, Session): "Implement refresh token pattern"
    - Multi-tenant / SaaS (when domain is not already SaaS): "Add tenant isolation fields"
    - Several modeling-pattern bullets per registered **project domain** category (catalog in Studio; **#616** expanded from one short line per domain)
- ✅ Industry-specific patterns (#616): multiple actionable patterns per domain (e.g. inventory/idempotency for e-commerce, ledger/idempotency for finance, FHIR-friendly identifiers for healthcare).
- ✅ Security hardening suggestions (#617): domain-based payment/PHI guidance, auth rate-limit hints, vault/logging guidance for secret-like properties, password-hash modeling, and webhook signature verification for webhook-style class names.
- ✅ Performance optimization suggestions (#618): cache namespacing/TTL, background job idempotency and retries, cursor/keyset pagination, search projections vs canonical entities, chunked bulk I/O, separating heavy binary metadata, and fan-out/timeline modeling when cache, queue, paging, search, export, media, or feed-style names appear on classes or reusable properties.

### AI Documentation Generation

**Auto-Generate Descriptions** 📋 PLANNED
- ✅ Generate property descriptions from names and types (#619 — Studio **Generate with AI** on property description fields; Ollama `property_description` task)
- ✅ Generate class descriptions from properties (#620 — Studio **Generate with AI** on class description field; Ollama `class_description` task)
- ✅ Generate operation summaries from path and method (#621 — Paths operation **Docs** tab **Generate summary & description**; Ollama `operation_description` task)
- ✅ Generate example values that make sense (#622 — property **Examples** **Generate example with AI** next to schema-based generate; Ollama `property_example` task)
- Support multiple languages (i18n)

### AI Layout Suggestions

**Intelligent Layout Suggestions** ✅ (#623)
- ✅ AI-powered layout recommendations:
    - ✅ Analyze schema structure and suggest best layout type (TB vs LR heuristic + schema depth)
    - ✅ Detect strongly connected components on the canvas graph
    - ✅ Suggest groupings based on relationships (weak components, SCC cycles — surfaced in metrics + suggestions)
    - ✅ Identify central/hub classes (degree on collapsed layout graph)
    - ✅ Recommend hierarchy roots (no incoming directed edges)
    - ✅ Optional Ollama narrative (`task: canvas_layout_recommendations`)
