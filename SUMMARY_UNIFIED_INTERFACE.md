# Unified Agent Interface

**Date:** 2026-03-28
**Status:** ✅ Complete

## Overview

Combined the separate `/chat` and `/workflow` pages into a single **unified agent interface** that provides both conversational chat and visual workflow execution in one view. Users can now see both the chat conversation and the workflow graph simultaneously, with a single prompt driving both visualizations.

---

## 🎯 Key Changes

### **1. Single Orchestration Process**

**Before:**
- `/chat` page → Used `/api/agent/stream` endpoint (chat-only)
- `/workflow` page → Used `/api/agent/execute` + `/api/agent/events` (workflow events only)
- **Separate execution paths** → inconsistent behavior
- Users had to switch tabs to see different views

**After:**
- **Unified view** → Both chat and workflow use the **same execution**
- Single prompt → dual event streams:
  - `/api/agent/stream` → Chat streaming (tokens, thinking, tools)
  - `/api/agent/events` → Workflow events (nodes, routing, tool execution)
- **Synchronized** → Both views update from the same agent run

---

### **2. Split-Panel Layout**

**Left Panel: Chat Interface**
- Message history with markdown rendering
- Streaming response with blinking cursor
- Thinking sections (auto-expanded for complex queries)
- Tool call sections (auto-expanded for >2 tools)
- Quick prompt buttons on empty state
- Chat input with auto-resize

**Right Panel: Workflow Graph (Toggle)**
- ReactFlow visualization
- Real-time node status updates (idle → running → completed)
- Tool nodes appearing dynamically below specialists
- Routing decision highlighted with animated edges
- MiniMap and controls for navigation

**Toggle Button:**
- "Show Workflow" / "Hide Workflow" button (top-right)
- Workflow panel shown only when there are messages
- Workflow hidden by default (clean chat-first UX)
- Width: 50/50 split when visible

---

### **3. Synchronized Event Streams**

Both streams run in parallel when a message is sent:

```typescript
// Workflow events stream (graph visualization)
cancelEventsRef.current = streamAgent(
  `${API_BASE}/api/agent/events?session_id=${sessionId}`,
  { onChunk: handleWorkflowEvent }
)

// Chat stream (conversation)
streamAgentFetch(
  `${API_BASE}/api/agent/stream?input=${text}&session_id=${sessionId}`,
  { onChunk: handleChatChunk, onToolCall, onThinking, onPlan, onRoute }
)
```

**Event Mapping:**
- `routing_decision` → Highlights specialist edge in workflow graph + shows route in chat
- `node` events → Updates node status in graph
- `tool` events → Adds tool nodes to graph + shows in chat tool section
- `plan` events → Shows plan steps in both chat thinking section and workflow log
- `thinking` events → Displayed in chat message reasoning section

---

## 📂 Files Created/Modified

### **New Files:**
1. ✅ `frontend-app/src/components/UnifiedAgentView.tsx` - Main unified component combining chat + workflow

### **Modified Files:**
1. ✅ `frontend-app/src/App.tsx` - Updated routing to use `UnifiedAgentView`
2. ✅ `frontend-app/src/components/layout/AppShell.tsx` - Removed "Workflow" tab, renamed "Chat" → "Agent"

### **Removed Routes:**
- ❌ `/workflow` route removed (functionality merged into `/chat`)

---

## 🎨 User Experience

### **Default State (Chat-First)**
1. User opens the app → sees full-width chat interface
2. Clean, distraction-free conversation view
3. Quick prompts for common queries
4. Workflow graph hidden by default

### **Complex Query (Workflow Visible)**
1. User asks complex question (e.g., multi-step planning)
2. User clicks "Show Workflow" button
3. Screen splits 50/50: chat left, workflow right
4. Both update in real-time as agent executes
5. User can see both conversation and execution flow simultaneously

### **Navigation**
- **⌘1** → Agent (unified chat + workflow)
- **⌘2** → Logs (detailed event trace)
- **⌘3** → Visuals (charts and analytics)
- **⌘K** → Clear all (chat + workflow + logs)

---

## 🚀 Benefits

### **For Users:**
✅ **Single prompt** → See both chat response AND execution graph
✅ **No tab switching** → Everything in one view
✅ **Contextual workflow** → Only shown when needed
✅ **Better transparency** → See what the agent is doing in real-time
✅ **Cleaner navigation** → 3 tabs instead of 4

### **For Developers:**
✅ **Single source of truth** → Same orchestration for both views
✅ **Consistent behavior** → No divergence between chat and workflow
✅ **Easier maintenance** → One component instead of two
✅ **Better DX** → Unified event handling logic

---

## 🧪 Testing

### **Basic Flow**
1. Navigate to `/` or `/chat`
2. Enter a query: "What's the weather in Hong Kong?"
3. **Expected:**
   - Chat shows streaming response
   - Workflow hidden (toggle available)
4. Click "Show Workflow"
5. **Expected:**
   - Screen splits 50/50
   - Workflow graph shows router → hk_weather → tool nodes
   - Both chat and workflow show same execution

### **Complex Query**
1. Enter: "Compare weather between VHHH and EGLL"
2. **Expected:**
   - Chat shows streaming with auto-expanded thinking section
   - Workflow (if visible) shows:
     - Router routes to `general` or `planning`
     - Multiple tool calls (get_metar for VHHH, get_metar for EGLL)
     - Tool nodes appear below specialist
   - Both views synchronized

### **Toggle Workflow**
1. Send a query
2. Click "Show Workflow" → panel appears (50/50 split)
3. Click "Hide Workflow" → panel disappears (full-width chat)
4. **Expected:** Toggle state persists during session

### **Clear All**
1. Send multiple queries
2. Click "Clear" or press ⌘K
3. **Expected:**
   - Chat messages cleared
   - Workflow graph reset to idle state
   - Logs cleared
   - Ready for new query

---

## 🔧 Technical Details

### **Component Architecture**

```
UnifiedAgentView
├── Chat Panel (left)
│   ├── Messages area
│   │   ├── MessageBubble (with ThinkingSection, ToolCallsSection)
│   │   └── Streaming indicator
│   └── ChatInput (fixed bottom)
└── Workflow Panel (right, toggleable)
    ├── Header (title + controls)
    └── ReactFlow
        ├── Agent nodes (router + specialists)
        ├── Tool nodes (dynamic)
        ├── Background
        ├── Controls
        └── MiniMap
```

### **State Management**

**Local State:**
- `showWorkflow: boolean` - Toggle workflow panel visibility
- `streamingMsg: Message | null` - Current streaming message
- `nodes / edges` - ReactFlow graph state

**Global State (Zustand):**
- `useChatStore` - Message history, loading state
- `useWorkflowStore` - Workflow logs (execution trace)

**Refs:**
- `sessionIdRef` - Persistent session ID across messages
- `cancelStreamRef` - Cancel chat stream
- `cancelEventsRef` - Cancel workflow events stream
- `activeToolIds` - Track tool node IDs for updates
- `toolCountPerSpecialist` - Position tool nodes vertically

### **Event Flow**

```
User sends message
    ↓
1. Add user message to chat store
2. Reset workflow graph
3. Start workflow events stream (subscribe first!)
4. Start chat stream
    ↓
Agent executes
    ↓
5. Workflow events → Update graph nodes/edges
6. Chat events → Update streaming message
    ↓
Both streams complete
    ↓
7. Add final message to chat store
8. Cleanup event streams
```

---

## 📊 Comparison: Before vs After

| **Aspect** | **Before** | **After** | **Improvement** |
|------------|------------|-----------|-----------------|
| **Pages** | 2 separate (Chat, Workflow) | 1 unified (Agent) | ✅ -50% routes |
| **Orchestration** | 2 different paths | 1 shared path | ✅ Consistency |
| **User Flow** | Tab switching required | Toggle panel optional | ✅ Better UX |
| **Navigation Tabs** | 4 tabs | 3 tabs | ✅ Simpler |
| **Event Sync** | Manual correlation | Automatic sync | ✅ Real-time |
| **Complexity** | Medium (2 components) | Low (1 component) | ✅ Easier maintenance |

---

## 🎓 Design Principles Applied

1. **Single Source of Truth** - One execution → multiple views
2. **Progressive Disclosure** - Workflow hidden until needed
3. **Real-time Feedback** - Both views update live
4. **Clean Default State** - Chat-first, workflow optional
5. **Keyboard-Friendly** - ⌘K clear, ⌘1/2/3 navigation

---

## 🔮 Future Enhancements

### **Short-term:**
1. **Persist workflow visibility** - Remember user preference in localStorage
2. **Workflow auto-show** - Automatically show for complex queries (planning mode)
3. **Resizable panels** - Drag divider to adjust chat/workflow width ratio
4. **Workflow export** - Download execution graph as image

### **Long-term:**
5. **Clickable nodes** - Click workflow node → jump to relevant chat message
6. **Playback mode** - Replay execution step-by-step
7. **Multi-session view** - Compare multiple query executions side-by-side
8. **Workflow templates** - Save and replay common execution patterns

---

## ✅ Migration Notes

### **For Users:**
- The `/workflow` URL still works but redirects to `/chat` (or shows 404)
- All functionality preserved - just combined into one view
- Keyboard shortcuts updated (⌘2 is now Logs, not Workflow)

### **For Developers:**
- `ChatView.tsx` and `WorkflowView.tsx` are now legacy (can be removed)
- Use `UnifiedAgentView.tsx` for all agent interaction
- Update any links to `/workflow` → `/chat`

---

**Questions?** Check the code comments in `UnifiedAgentView.tsx` or reach out to the team.
