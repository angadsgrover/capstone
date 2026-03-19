# React Native Mobile App Guide

## Overview

The capstone frontend was designed with portability in mind — the **shared layer** (`types`, `services`, `state`) works seamlessly with React Native with minimal modifications. This guide demonstrates how to create a React Native mobile app (iOS/Android) that reuses the existing shared logic.

## Architecture: Shared Layer Portability

```
frontend-app/ (Web)              mobile-app/ (Native)
├── src/shared/                 ├── src/shared/           ← PORTABLE
│   ├── types/                  │   ├── types/            ← 100% portable
│   ├── services/               │   ├── services/         ← 95% portable (fetch/EventSource)
│   └── state/                  │   └── state/            ← 100% portable (Zustand)
├── src/components/             ├── src/components/       ← Platform-specific UI
│   ├── chat/                   │   ├── chat/             ← Native equivalents
│   ├── workflow/               │   ├── workflow/         ← React Native Paper
│   └── logs/                   │   └── logs/             ← Native Lists
```

### Key Portability Points
1. **Types** (`types/agent.ts`, `types/workflow.ts`) → 100% portable (no DOM dependencies)
2. **Services** (`agentService.ts`, `streamService.ts`) → 95% portable (use React Native polyfills for EventSource)
3. **State** (`chatStore.ts`, `workflowStore.ts`) → 100% portable (Zustand works identically)
4. **Components** → Platform-specific (native UI toolkit)

---

## Quick Start with Expo (Recommended)

### 1. Initialize React Native App

```bash
# Install Expo CLI
npm install -g expo-cli

# Create new app
cd capstone/
npx create-expo-app mobile-app --template blank-typescript

cd mobile-app
```

### 2. Install Dependencies

```bash
# Core dependencies
npm install zustand @react-navigation/native @react-navigation/bottom-tabs
npm install react-native-paper react-native-safe-area-context react-native-screens
npm install react-native-markdown-display react-native-svg

# EventSource polyfill (for SSE streaming)
npm install react-native-sse event-source-polyfill

# Async Storage (for persistence)
npm install @react-native-async-storage/async-storage
```

### 3. Copy Shared Layer

```bash
# Copy portable shared layer from web app
cp -r ../frontend-app/src/shared ./src/
```

### 4. Update Path Aliases

**`tsconfig.json`**:
```json
{
  "extends": "expo/tsconfig.base",
  "compilerOptions": {
    "baseUrl": ".",
    "paths": {
      "@/*": ["src/*"],
      "@/shared/*": ["src/shared/*"]
    },
    "strict": true
  }
}
```

**`babel.config.js`**:
```javascript
module.exports = function (api) {
  api.cache(true);
  return {
    presets: ['babel-preset-expo'],
    plugins: [
      [
        'module-resolver',
        {
          root: ['./src'],
          extensions: ['.ios.js', '.android.js', '.js', '.ts', '.tsx', '.json'],
          alias: {
            '@': './src',
            '@/shared': './src/shared',
          },
        },
      ],
    ],
  };
};
```

Install babel plugin:
```bash
npm install --save-dev babel-plugin-module-resolver
```

---

## Portable Shared Layer Modifications

### 1. `src/shared/services/streamService.ts` (Minor Update)

The web version uses native `EventSource`. For React Native, use a polyfill:

```typescript
// src/shared/services/streamService.ts (React Native version)
import { NativeEventSource, EventSourcePolyfill } from 'event-source-polyfill';

// Use polyfill for EventSource
const EventSource = NativeEventSource || EventSourcePolyfill;

export function subscribeToEvents(
  sessionId: string,
  onEvent: (event: WorkflowEvent) => void,
  onError?: (error: Error) => void,
): () => void {
  const eventSource = new EventSource(
    `${API_BASE_URL}/api/agent/events?session_id=${sessionId}`,
    {
      headers: {
        // Add auth headers if needed
      },
    }
  );

  // ... rest of implementation (same as web)
}
```

### 2. `src/shared/state/chatStore.ts` (Storage Update)

Replace `localStorage` with React Native's AsyncStorage:

```typescript
// src/shared/state/chatStore.ts (React Native version)
import AsyncStorage from '@react-native-async-storage/async-storage';
import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';

export const useChatStore = create<ChatStore>()(
  persist(
    (set, get) => ({
      messages: [],
      addMessage: (message) => set((state) => ({
        messages: [...state.messages, message],
      })),
      // ... rest of store
    }),
    {
      name: 'chat-storage',
      storage: createJSONStorage(() => AsyncStorage),  // React Native storage
    }
  )
);
```

---

## Native Components

### 1. Chat View (`src/components/chat/ChatView.tsx`)

```tsx
import React, { useState, useEffect, useRef } from 'react';
import { View, FlatList, StyleSheet, KeyboardAvoidingView, Platform } from 'react-native';
import { TextInput, Button, ActivityIndicator } from 'react-native-paper';
import { useChatStore } from '@/shared/state/chatStore';
import { sendMessage, streamAgent } from '@/shared/services/agentService';
import MessageBubble from './MessageBubble';

export default function ChatView() {
  const { messages, addMessage } = useChatStore();
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const flatListRef = useRef<FlatList>(null);

  const handleSend = async () => {
    if (!input.trim()) return;

    const userMessage = {
      id: Date.now().toString(),
      role: 'user' as const,
      content: input,
      timestamp: new Date(),
    };

    addMessage(userMessage);
    setInput('');
    setLoading(true);

    try {
      // Use streaming service (SSE)
      const abortController = new AbortController();
      let assistantContent = '';

      await streamAgent(
        input,
        'default-session',
        (text) => {
          // Accumulate chunks
          assistantContent += text;
        },
        abortController.signal
      );

      // Add complete response
      addMessage({
        id: Date.now().toString(),
        role: 'assistant',
        content: assistantContent,
        timestamp: new Date(),
      });
    } catch (error) {
      console.error('Send error:', error);
    } finally {
      setLoading(false);
    }
  };

  // Auto-scroll to bottom
  useEffect(() => {
    flatListRef.current?.scrollToEnd({ animated: true });
  }, [messages]);

  return (
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
      keyboardVerticalOffset={90}
    >
      <FlatList
        ref={flatListRef}
        data={messages}
        keyExtractor={(item) => item.id}
        renderItem={({ item }) => <MessageBubble message={item} />}
        contentContainerStyle={styles.listContent}
      />

      <View style={styles.inputContainer}>
        <TextInput
          style={styles.textInput}
          mode="outlined"
          placeholder="Ask about weather, flights..."
          value={input}
          onChangeText={setInput}
          onSubmitEditing={handleSend}
          disabled={loading}
          multiline
          maxLength={500}
        />
        <Button
          mode="contained"
          onPress={handleSend}
          loading={loading}
          disabled={loading || !input.trim()}
          style={styles.sendButton}
        >
          Send
        </Button>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#fff',
  },
  listContent: {
    padding: 16,
  },
  inputContainer: {
    flexDirection: 'row',
    padding: 16,
    borderTopWidth: 1,
    borderTopColor: '#e0e0e0',
    backgroundColor: '#f9f9f9',
  },
  textInput: {
    flex: 1,
    marginRight: 8,
  },
  sendButton: {
    alignSelf: 'center',
  },
});
```

### 2. Message Bubble (`src/components/chat/MessageBubble.tsx`)

```tsx
import React from 'react';
import { View, StyleSheet } from 'react-native';
import { Card, Text } from 'react-native-paper';
import Markdown from 'react-native-markdown-display';
import type { Message } from '@/shared/types/agent';

interface Props {
  message: Message;
}

export default function MessageBubble({ message }: Props) {
  const isUser = message.role === 'user';

  return (
    <View style={[styles.container, isUser ? styles.userContainer : styles.assistantContainer]}>
      <Card style={[styles.bubble, isUser ? styles.userBubble : styles.assistantBubble]}>
        <Card.Content>
          {isUser ? (
            <Text style={styles.userText}>{message.content}</Text>
          ) : (
            <Markdown style={markdownStyles}>{message.content}</Markdown>
          )}
          <Text style={styles.timestamp}>
            {new Date(message.timestamp).toLocaleTimeString()}
          </Text>
        </Card.Content>
      </Card>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    marginVertical: 4,
  },
  userContainer: {
    alignItems: 'flex-end',
  },
  assistantContainer: {
    alignItems: 'flex-start',
  },
  bubble: {
    maxWidth: '80%',
  },
  userBubble: {
    backgroundColor: '#007AFF',
  },
  assistantBubble: {
    backgroundColor: '#E5E5EA',
  },
  userText: {
    color: '#fff',
  },
  timestamp: {
    fontSize: 10,
    color: '#999',
    marginTop: 4,
  },
});

const markdownStyles = {
  body: {
    color: '#000',
  },
  code_inline: {
    backgroundColor: '#f0f0f0',
    paddingHorizontal: 4,
    borderRadius: 3,
  },
  code_block: {
    backgroundColor: '#f0f0f0',
    padding: 8,
    borderRadius: 4,
  },
};
```

### 3. Main Navigation (`App.tsx`)

```tsx
import React from 'react';
import { NavigationContainer } from '@react-navigation/native';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { Provider as PaperProvider } from 'react-native-paper';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/MaterialCommunityIcons';

import ChatView from './src/components/chat/ChatView';
import WorkflowView from './src/components/workflow/WorkflowView';  // Placeholder
import LogsView from './src/components/logs/LogsView';              // Placeholder

const Tab = createBottomTabNavigator();

export default function App() {
  return (
    <SafeAreaProvider>
      <PaperProvider>
        <NavigationContainer>
          <Tab.Navigator
            screenOptions={({ route }) => ({
              tabBarIcon: ({ color, size }) => {
                const icons: Record<string, string> = {
                  Chat: 'message-text',
                  Workflow: 'graph',
                  Logs: 'format-list-bulleted',
                };
                return <Icon name={icons[route.name]} size={size} color={color} />;
              },
              tabBarActiveTintColor: '#007AFF',
              tabBarInactiveTintColor: 'gray',
            })}
          >
            <Tab.Screen name="Chat" component={ChatView} />
            <Tab.Screen name="Workflow" component={WorkflowView} />
            <Tab.Screen name="Logs" component={LogsView} />
          </Tab.Navigator>
        </NavigationContainer>
      </PaperProvider>
    </SafeAreaProvider>
  );
}
```

---

## Platform-Specific Considerations

### 1. ReactFlow → React Native Skia/SVG

The web's `WorkflowView` uses ReactFlow (DOM-based). For mobile, use **React Native Skia** or **react-native-svg**:

```bash
npm install @shopify/react-native-skia
# or
npm install react-native-svg
```

**Simplified workflow visualization** (using SVG):
```tsx
// src/components/workflow/WorkflowView.tsx (Native version)
import Svg, { Circle, Line, Text } from 'react-native-svg';

export default function WorkflowView() {
  // Render workflow as SVG instead of ReactFlow
  return (
    <Svg height="400" width="100%">
      <Circle cx="50" cy="50" r="20" fill="blue" />
      <Line x1="50" y1="70" x2="50" y2="150" stroke="black" />
      <Text x="30" y="55" fill="white" fontSize="12">
        Router
      </Text>
    </Svg>
  );
}
```

### 2. Logs → Native FlatList

Replace `<table>` with `FlatList`:
```tsx
import { FlatList, Text, View } from 'react-native';
import { useWorkflowStore } from '@/shared/state/workflowStore';

export default function LogsView() {
  const { events } = useWorkflowStore();

  return (
    <FlatList
      data={events}
      keyExtractor={(item, index) => index.toString()}
      renderItem={({ item }) => (
        <View style={{ padding: 12, borderBottomWidth: 1, borderColor: '#eee' }}>
          <Text style={{ fontWeight: 'bold' }}>{item.event_type}</Text>
          <Text>{item.details}</Text>
        </View>
      )}
    />
  );
}
```

---

## Configuration

### API Base URL

**`src/shared/services/agentService.ts`** (update for mobile):
```typescript
// Use environment variable or platform-specific config
const API_BASE_URL =
  process.env.EXPO_PUBLIC_API_URL || 'http://localhost:8000';  // iOS Simulator: localhost works
  // Android Emulator: use 'http://10.0.2.2:8000'
  // Physical device: use your computer's IP (e.g., 'http://192.168.1.100:8000')
```

**`.env` (Expo)**:
```bash
EXPO_PUBLIC_API_URL=http://192.168.1.100:8000
```

---

## Running the App

### iOS Simulator
```bash
npm start
# Press 'i' for iOS simulator
```

### Android Emulator
```bash
npm start
# Press 'a' for Android emulator
```

### Physical Device
```bash
# Install Expo Go app on your phone
npm start
# Scan QR code with Expo Go (iOS) or camera (Android)
```

---

## Key Differences: Web vs Native

| Feature | Web (`frontend-app`) | Native (`mobile-app`) |
|---------|---------------------|---------------------|
| **UI Framework** | React + Tailwind CSS | React Native + Paper |
| **Navigation** | React Router | React Navigation |
| **Workflow Viz** | ReactFlow (DOM) | Skia/SVG |
| **Storage** | localStorage | AsyncStorage |
| **SSE Streaming** | Native EventSource | Polyfill (react-native-sse) |
| **Markdown** | react-markdown | react-native-markdown-display |
| **Icons** | lucide-react | react-native-vector-icons |

---

## Testing Strategy

1. **Shared Layer**: Already tested via web app (types, services, state)
2. **Native Components**: Test on iOS + Android simulators
3. **API Integration**: Test against local backend (`localhost:8000` for iOS, `10.0.2.2:8000` for Android emulator)
4. **Streaming**: Verify SSE works with polyfill on both platforms

---

## Future Enhancements

1. **Offline Mode**: Cache responses with AsyncStorage, sync when online
2. **Push Notifications**: Alert on weather changes, safety events
3. **Voice Input**: Speech-to-text for queries
4. **Dark Mode**: React Native Paper theme switching
5. **Biometric Auth**: Face ID/Touch ID for secure sessions
6. **iPad Optimization**: Multi-pane layout (split-view chat + workflow)
7. **Watchlist**: Pin favorite airports for quick weather checks

---

## Deployment

### iOS (App Store)
```bash
eas build --platform ios
# Follow Expo EAS Build guide: https://docs.expo.dev/build/introduction/
```

### Android (Google Play)
```bash
eas build --platform android
```

---

## Summary

The **shared layer portability** allows you to:
1. ✅ Reuse 95% of business logic (types, services, state)
2. ✅ Focus only on native UI components
3. ✅ Maintain consistency between web and mobile
4. ✅ Test once, deploy everywhere

Next steps:
1. Copy `frontend-app/src/shared/` to `mobile-app/src/shared/`
2. Implement native Chat/Workflow/Logs views using components above
3. Test on iOS + Android simulators
4. Deploy to app stores via Expo EAS Build

**Total Effort**: ~2-3 days for a working MVP (since shared logic is already done!)
