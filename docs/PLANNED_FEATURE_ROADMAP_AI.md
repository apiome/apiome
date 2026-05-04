# AI Planned Feature Roadmap

This outlines the planned features for integrating AI capabilities into Objectified.


### Preparation

- Install Ollama Cluster
- Set up Mac Mini cluster using EXO
- Deploy Ollama with Qwen 2.5 and Llama 3.2 models
- Configure network access and security
- Test Ollama API connectivity from Objectified backend
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

**Quick Actions from Chat** 📋 PLANNED
- 📋 AI responses include action buttons:
    - 📋 "Create this class" → One-click class creation
    - 📋 "Add these properties" → Batch property addition
    - 📋 "Apply to current class" → Modify selected class
    - "Generate path for this" → Create CRUD endpoints
    - 📋 "Copy to clipboard" → Copy generated JSON/YAML
- 📋 Preview changes before applying
- Undo AI-generated changes

| Ticket | Feature Description             |
|--------|---------------------------------|
| #518   | Quick Actions from Chat         |
| #519   | Preview changes before applying |

### Ollama Integration

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

**Ollama API Integration** 📋 PLANNED
- 📋 **Streaming Responses**:
    - ✅ Server-Sent Events (SSE) for streaming (#520)
    - ✅ Token-by-token usage display (#521)
    - ✅ Cancel generation mid-stream (#522)
    - ✅ Progress indication (#523)
- 📋 **Caching**:
    - ✅ Cache common queries (#524)
    - ✅ Semantic similarity matching (#525)
    - 📋 Cache invalidation on schema changes
- 📋 **Guardrails**:
    - 📋 Prompt filtering for sensitive content
    - 📋 Response filtering for PII
    - 📋 Rate limiting enforcement
    - 📋Logging and audit trails

| Ticket | Feature Description                                 |
|--------|-----------------------------------------------------|
| #526   | Cache invalidation on schema changes                |
| #527   | Implementation of Guardrails for prompts/responses  |

### Natural Language to Schema

**Schema Generation from Description** 📋 PLANNED
- 📋 **Input Methods**:
    - 📋 Free-form text description
    - 📋 Structured prompts with templates
    - 📋 Voice input (speech-to-text)
    - 📋 Paste requirements document
- 📋 **Example Prompts**:
    - 📋 "Create a User class with email, password hash, created date, and roles array"
    - 📋 "I need an e-commerce order with line items, shipping address, and payment info"
    - 📋 "Generate a blog post schema with author reference, tags, and comments"
    - 📋 "Create a REST API for managing a todo list application"
- 📋 **Generation Output**:
    - 📋 Preview generated schema before creation
    - 📋 JSON Schema format display
    - 📋 Property list with types
    - 📋 Relationship suggestions
- 📋 **Iterative Refinement**:
    - 📋 "Add a phone number field"
    - 📋 "Make email required"
    - 📋 "Add validation for password length"
    - 📋 "Include timestamps for audit"

| Ticket | Feature Description                                      |
|--------|----------------------------------------------------------|
| #267   | Adds the ability to generate a schema from a description |
| #268   | Adds example prompts                                     |
| #528   | Preview generated schema before creation                 |
| #529   | JSON Schema format display on preview                    |
| #530   | Property list with types on preview                      |
| #531   | Relationship suggestions on preview                      |
| #532   | Iterative refinement of generated schemas                |

### AI-Powered Property Suggestions

**Smart Property Recommendations** 📋 PLANNED
- 📋 **Trigger Conditions**:
    - 📋 When creating a new class
    - 📋 When class name is entered
    - 📋 On-demand via chat or button
    - 📋 After adding first few properties
- 📋 **Suggestion Types**:
    - 📋 Common properties for class type (e.g., "User" → email, password, name)
    - 📋 Missing standard properties (e.g., id, createdAt, updatedAt)
    - 📋 Related properties based on existing ones
    - 📋 Industry-standard properties (FHIR for healthcare, etc.)
- 📋 **Suggestion UI**:
    - 📋 Property suggestion dropdown
    - 📋 Bulk accept/reject
    - 📋 Customize before adding
    - 📋 "Add all suggested" button
    - 📋 Explanation for each suggestion

| Ticket | Feature Description                                |
|--------|----------------------------------------------------|
| #269   | Adds the ability to suggest properties based on AI |
| #270   | Adds a property suggestion dropdown                |
| #271   | Adds bulk accept/reject for property suggestions   |
| #272   | Adds customization before adding                   |
| #273   | Adds explanations for each suggestion              |
| #274   | Adds "Add all suggested" button                    |
| #275   | Adds trigger conditions for the Suggestion UI      |
| #276   | Adds analyze button for properties analysis        |

**Type and Constraint Inference** 📋 PLANNED
- 📋 Suggest type based on property name:
    - 📋 `email` → string with email format
    - 📋 `createdAt` → string with date-time format
    - 📋 `age` → integer with minimum 0
    - 📋 `price` → number with minimum 0
    - 📋 `isActive` → boolean
- 📋 Suggest constraints:
    - 📋 String length limits
    - 📋 Numeric ranges
    - 📋 Pattern validation
    - 📋 Required vs optional

| Ticket | Feature Description                        |
|--------|--------------------------------------------|
| #277   | Adds type inference based on property name |
| #278   | Adds constraint suggestions for properties |

### AI Schema Review & Improvement

**Improvement Suggestions** 📋 PLANNED
- 📋 "Consider adding pagination to this list endpoint"
- 📋 "This schema could benefit from inheritance using allOf"
- 📋 "Add a discriminator for this polymorphic type"
- 📋 "Consider breaking this large schema into smaller components"
- 📋 "Add error responses for common failure scenarios"

| Ticket | Feature Description             |
|--------|---------------------------------|
| #495   | Adds AI improvement suggestions |

**Actionable Recommendations** 📋 PLANNED
- 📋 AI-powered suggestions for improvement:
    - 📋 "Add descriptions to 12 classes to improve docs score"
    - 📋 "Rename 5 properties to follow camelCase convention"
    - 📋 "Split 'User' class - it has 28 properties (recommended max: 15)"
    - 📋 "Add pagination to 'GET /users' endpoint"
- 📋 Prioritized action items (quick wins first)
- 📋 Estimated score impact for each fix
- 📋 Bulk apply recommendations

| Ticket | Feature Description                    |
|--------|----------------------------------------|
| #253   | AI powered suggestions for improvement |
| #254   | Prioritized action items               |
| #255   | Estimated score impact for each fix    |
| #256   | Add bulk apply recommendations         |

### AI Properties Insights

**Property Creation Suggestions** 📋 PLANNED
- 📋 Common property sets for specific class types
- 📋 Industry-standard property recommendations
- 📋 Context-aware property suggestions based on existing schema
- 📋 Property naming convention analysis

| Ticket | Feature Description              |
|--------|----------------------------------|
| #609   | AI Property Creation Suggestions |

### AI Schema Health Insights

**Schema Complexity Analysis** 📋 PLANNED
- 📋 Cognitive complexity score per class
- 📋 Dependency graph complexity
- 📋 Cyclomatic complexity for conditional schemas
- 📋 Maintainability index
- 📋 Technical debt metrics

| Ticket | Feature Description                           |
|--------|-----------------------------------------------|
| #610   | AI Schema Complexity Analysis                 |
| #611   | Dependency Graph Complexity                   |
| #612   | Cyclomatic Complexity for Conditional Schemas |
| #613   | Maintainability Index                         |
| #614   | Technical Debt Metrics                        |

**Best Practice Suggestions** 📋 PLANNED
- 📋 Context-aware tips based on schema type:
    - E-commerce: "Consider adding inventory tracking"
    - Authentication: "Implement refresh token pattern"
    - Multi-tenant: "Add tenant isolation fields"
- 📋 Industry-specific patterns
- Security hardening suggestions
- Performance optimization tips

| Ticket | Feature Description            |
|--------|--------------------------------|
| #615   | AI Best Practice Suggestions   |
| #616   | Industry-specific Patterns     |
| #617   | Security Hardening Suggestions |
| #618   | Performance Optimization Tips  |

### AI Documentation Generation

**Auto-Generate Descriptions** 📋 PLANNED
- 📋 Generate property descriptions from names and types
- 📋 Generate class descriptions from properties
- 📋 Generate operation summaries from path and method
- 📋 Generate example values that make sense
- Support multiple languages (i18n)

| Ticket | Feature Description                                        |
|--------|------------------------------------------------------------|
| #619   | Auto-Generate Descriptions                                 |
| #620   | Auto-Generate descriptions for classes                     |
| #621   | Operations summaries and descriptions from path and method |
| #622   | Generate example values that make sense                    |

### AI Layout Suggestions

**Intelligent Layout Suggestions** 📋 PLANNED
- AI-powered layout recommendations:
    - 📋 Analyze schema structure and suggest best layout type
    - 📋 Detect strongly connected components
    - 📋 Suggest groupings based on relationships
    - 📋 Identify central/hub classes
    - 📋 Recommend hierarchy roots

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|
|| #623   | Intelligent Layout Suggestions                  |

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
