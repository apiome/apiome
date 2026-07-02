# LLM-Powered Import Feature

## Overview
Generate OpenAPI 3.1.0 specifications using natural language through an Ollama-powered chat interface with real-time SSE streaming.

## Components Created

### API Routes
1. `/api/ollama/models` - Fetches available models
2. `/api/ollama/chat` - Streams chat responses via SSE

### UI Components
- `LLMImportDialog.tsx` - Main chat interface
- Integrated into `ImportDialog.tsx` as "AI Assistant" option

## Configuration
- **Ollama Server**: Configured via `OLLAMA_BASE_URL` environment variable
  - Default: `http://localhost:11434`
  - Set in `.env` file: `OLLAMA_BASE_URL=http://your-ollama-server:11434`
- **Supported Format**: OpenAPI 3.1.0
- **Streaming**: Server-Sent Events (SSE)

## Usage Flow
1. Click "New Import" in Projects page
2. Select "AI Assistant" option
3. Choose a model from dropdown
4. Describe your API in natural language
5. Click "Import This Spec" when JSON block appears
6. Continue with normal import workflow

## Features
- Real-time streaming responses
- Conversation context memory
- Multiple model selection
- Quick-start templates
- Direct import to analysis pipeline
- Iterative refinement support

## Files Modified/Created
- `src/app/api/ollama/models/route.ts` (new)
- `src/app/api/ollama/chat/route.ts` (new)
- `src/app/components/ade/dashboard/LLMImportDialog.tsx` (new)
- `src/app/components/ade/dashboard/ImportDialog.tsx` (modified)

## Example Usage
```
User: "Create a blog API with posts and comments"
AI: [Generates complete OpenAPI 3.1.0 spec in JSON code block]
User: Click "Import This Spec" button
```

## Technical Details
- Uses Next.js App Router API routes
- SSE for real-time streaming
- React hooks for state management
- Radix UI for accessible components
- Conversation history maintained client-side

