# AI-Powered Import - Visual Layout with Caveat

## Dialog Layout (with Warning Banner)

```
┌────────────────────────────────────────────────────────────┐
│ ✨ AI-Powered Import                              [X]      │
│    Generate OpenAPI specifications using natural language   │
├────────────────────────────────────────────────────────────┤
│ ⚠️  Important: AI can make mistakes. Always review and     │
│     verify generated specifications before importing.       │
├────────────────────────────────────────────────────────────┤
│ Model: [llama3.2              ▼]  [Reset Conversation]    │
├────────────────────────────────────────────────────────────┤
│                                                            │
│                      🤖 Start a Conversation                │
│                                                            │
│    Describe the API you want to create, and I'll generate │
│    an OpenAPI 3.1.0 specification for you.                │
│                                                            │
│    💬 Create a blog API with posts and comments           │
│    🛒 E-commerce API with products and orders              │
│    🔐 User management with authentication                  │
│                                                            │
├────────────────────────────────────────────────────────────┤
│ [Type your message here...                    ] [Send]     │
└────────────────────────────────────────────────────────────┘
```

## Color Scheme

### Warning Banner

**Light Mode:**
```
┌────────────────────────────────────────────────────────┐
│ 🔺 Important: AI can make mistakes. Always review and │
│    verify generated specifications before importing.   │
└────────────────────────────────────────────────────────┘
Background: Light Yellow (#FEFCE8)
Border: Yellow (#FDE68A)
Icon: Dark Yellow (#CA8A04)
Text: Very Dark Yellow (#713F12)
```

**Dark Mode:**
```
┌────────────────────────────────────────────────────────┐
│ 🔺 Important: AI can make mistakes. Always review and │
│    verify generated specifications before importing.   │
└────────────────────────────────────────────────────────┘
Background: Dark Yellow with opacity (#78350F with 20% opacity)
Border: Dark Yellow (#854D0E)
Icon: Light Yellow (#FACC15)
Text: Light Yellow (#FEF08A)
```

## With Active Conversation

```
┌────────────────────────────────────────────────────────────┐
│ ✨ AI-Powered Import                              [X]      │
│    Generate OpenAPI specifications using natural language   │
├────────────────────────────────────────────────────────────┤
│ ⚠️  Important: AI can make mistakes. Always review and     │
│     verify generated specifications before importing.       │
├────────────────────────────────────────────────────────────┤
│ Model: [llama3.2              ▼]  [Reset Conversation]    │
├────────────────────────────────────────────────────────────┤
│                                                            │
│                                            [User Message]  │
│  Create a REST API for a blog with posts and comments     │
│                                                            │
│  🤖 [Assistant Response]                                   │
│  I'll create an OpenAPI 3.1.0 specification for a blog    │
│  API with posts and comments. Here's the spec:            │
│                                                            │
│  ```json                                                   │
│  {                                                         │
│    "openapi": "3.1.0",                                     │
│    "info": {                                               │
│      "title": "Blog API",                                  │
│      "version": "1.0.0"                                    │
│    }                                                       │
│  }                                                         │
│  ```                                                       │
│  [Import This Spec]                                        │
│                                                            │
├────────────────────────────────────────────────────────────┤
│ [Add more requirements...                     ] [Send]     │
└────────────────────────────────────────────────────────────┘
```

## Warning Banner Visibility States

### Always Visible
The warning banner is **always visible** regardless of:
- ✅ Dialog state (empty/active conversation)
- ✅ Model selection
- ✅ Message history
- ✅ Loading states

### Cannot Be Dismissed
- ❌ No close button
- ❌ No checkbox to hide
- ❌ No "Don't show again" option

This ensures users are consistently reminded of AI limitations.

## Placement Rationale

### Why Second Position (After Header)?
1. **Immediate Visibility**: Users see it right when dialog opens
2. **Can't Miss It**: Bright yellow color stands out
3. **Context**: Appears before any interaction
4. **Persistent**: Stays visible as users scroll through conversation
5. **Non-Intrusive**: Doesn't block main interaction area

### Why Not Dismissible?
- Critical safety information
- Should be visible throughout the entire session
- Reinforces responsible AI usage
- Protects users from blindly trusting AI output

## Responsive Behavior

### Desktop (Large Screen)
```
Full width banner with icon and text inline
Icon: 16px (h-4 w-4)
Padding: 12px horizontal, 12px vertical
```

### Tablet/Mobile
```
Full width banner (same as desktop)
Text may wrap to multiple lines
Icon remains at top-left
```

## User Flow with Warning

```
1. User clicks "AI Assistant" in Import Dialog
        ↓
2. LLM Dialog opens
        ↓
3. User immediately sees:
   - Header: "AI-Powered Import"
   - WARNING BANNER ⚠️ (PROMINENT)
   - Model selection
        ↓
4. User reads warning before proceeding
        ↓
5. User generates specification with awareness
        ↓
6. User reviews generated spec (encouraged by warning)
        ↓
7. User imports only after verification
```

## Comparison: Before vs After

### Before (No Warning)
```
┌──────────────────────────────────┐
│ ✨ AI-Powered Import     [X]    │
│ Generate OpenAPI specs           │
├──────────────────────────────────┤
│ Model: [llama3.2      ▼]        │
├──────────────────────────────────┤
│ [Chat Area]                      │
```
⚠️ Risk: Users might trust AI output blindly

### After (With Warning)
```
┌──────────────────────────────────┐
│ ✨ AI-Powered Import     [X]    │
│ Generate OpenAPI specs           │
├──────────────────────────────────┤
│ ⚠️ Important: AI can make        │
│   mistakes...                    │ ← NEW
├──────────────────────────────────┤
│ Model: [llama3.2      ▼]        │
├──────────────────────────────────┤
│ [Chat Area]                      │
```
✅ Benefit: Users are informed and cautious

## Implementation Success Metrics

✅ **Visibility**: Warning appears in every LLM dialog session
✅ **Prominence**: Yellow banner is impossible to miss
✅ **Clarity**: Message is clear and actionable
✅ **Persistence**: Warning remains throughout session
✅ **Accessibility**: High contrast, icon + text

---

**The warning banner successfully implements responsible AI practices by ensuring users are always aware that AI-generated content requires human verification.**

