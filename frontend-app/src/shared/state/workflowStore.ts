import { create } from 'zustand'
import { WorkflowNode, WorkflowEdge, WorkflowInput, WorkflowResult } from '../types/workflow'

interface WorkflowStore {
  // State
  nodes: WorkflowNode[]
  edges: WorkflowEdge[]
  inputs: WorkflowInput
  result: WorkflowResult | null
  isExecuting: boolean
  logs: string[]

  // Actions
  setNodes: (nodes: WorkflowNode[]) => void
  setEdges: (edges: WorkflowEdge[]) => void
  updateNode: (id: string, node: Partial<WorkflowNode>) => void
  setInputs: (inputs: WorkflowInput) => void
  setResult: (result: WorkflowResult) => void
  setExecuting: (executing: boolean) => void
  addLog: (message: string) => void
  clearLogs: () => void
  reset: () => void
}

export const useWorkflowStore = create<WorkflowStore>((set) => ({
  nodes: [],
  edges: [],
  inputs: {},
  result: null,
  isExecuting: false,
  logs: [],

  setNodes: (nodes) => set({ nodes }),

  setEdges: (edges) => set({ edges }),

  updateNode: (id, node) =>
    set((state) => ({
      nodes: state.nodes.map((n) => (n.id === id ? { ...n, ...node } : n)),
    })),

  setInputs: (inputs) => set({ inputs }),

  setResult: (result) => set({ result }),

  setExecuting: (executing) => set({ isExecuting: executing }),

  addLog: (message) =>
    set((state) => ({
      logs: [...state.logs, `[${new Date().toLocaleTimeString()}] ${message}`],
    })),

  clearLogs: () => set({ logs: [] }),

  reset: () =>
    set({
      nodes: [],
      edges: [],
      inputs: {},
      result: null,
      isExecuting: false,
      logs: [],
    }),
}))
