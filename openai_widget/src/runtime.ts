import type { QueryCurrentFloorData, SetActiveFloorData } from './types';

type JsonRpcEnvelope = {
  jsonrpc?: string;
  method?: string;
  params?: Record<string, unknown>;
  result?: unknown;
};

type WidgetState<T> =
  | { status: 'loading'; data: null; error?: undefined }
  | { status: 'ready'; data: T; error?: undefined }
  | { status: 'empty'; data: null; error?: undefined }
  | { status: 'error'; data: null; error: string };

declare global {
  interface Window {
    structuredContent?: unknown;
    __structuredContent?: unknown;
    openai?: {
      toolOutput?: {
        structuredContent?: unknown;
      };
    };
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

function hasFields(value: unknown): value is Record<string, unknown> {
  return isRecord(value) && Object.keys(value).length > 0;
}

function readCompatibilityPayload(): Record<string, unknown> | null {
  const previewNode = document.getElementById('widget-preview-data');
  if (previewNode && previewNode.textContent) {
    try {
      const parsed = JSON.parse(previewNode.textContent);
      if (hasFields(parsed)) return parsed;
    } catch {
      // ignored: preview payload is optional
    }
  }

  if (hasFields(window.structuredContent)) return window.structuredContent;
  if (hasFields(window.__structuredContent)) return window.__structuredContent;
  const compat = window.openai?.toolOutput?.structuredContent;
  if (hasFields(compat)) return compat;
  return null;
}

function parseBridgeMessage(raw: unknown): Record<string, unknown> | null {
  const data = typeof raw === 'string' ? safeJsonParse(raw) : raw;
  if (!isRecord(data)) return null;

  const envelope = data as JsonRpcEnvelope;
  if (envelope.jsonrpc !== '2.0') return null;
  if (!envelope.method || !envelope.method.startsWith('ui/')) return null;

  const params = isRecord(envelope.params) ? envelope.params : {};
  if (hasFields(params.structuredContent)) return params.structuredContent;

  if (isRecord(params.result) && hasFields((params.result as Record<string, unknown>).structuredContent)) {
    return (params.result as Record<string, unknown>).structuredContent as Record<string, unknown>;
  }

  if (isRecord(envelope.result) && hasFields((envelope.result as Record<string, unknown>).structuredContent)) {
    return (envelope.result as Record<string, unknown>).structuredContent as Record<string, unknown>;
  }

  return null;
}

function safeJsonParse(value: string): unknown {
  try {
    return JSON.parse(value);
  } catch {
    return null;
  }
}

class BridgeStore<T> {
  private state: WidgetState<T> = { status: 'loading', data: null };
  private listeners = new Set<() => void>();
  private initialized = false;

  constructor() {
    window.addEventListener('message', (event: MessageEvent) => {
      const payload = parseBridgeMessage(event.data);
      if (payload) this.setReady(payload as T);
    });
  }

  private setReady(data: T) {
    this.state = { status: 'ready', data };
    this.emit();
  }

  private setEmpty() {
    if (this.state.status !== 'ready') {
      this.state = { status: 'empty', data: null };
      this.emit();
    }
  }

  init() {
    if (this.initialized) return;
    this.initialized = true;
    const compat = readCompatibilityPayload();
    if (compat) this.setReady(compat as T);
    else this.setEmpty();
  }

  getSnapshot(): WidgetState<T> {
    return this.state;
  }

  subscribe(listener: () => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  private emit() {
    for (const listener of this.listeners) listener();
  }
}

const setActiveStore = new BridgeStore<SetActiveFloorData>();
const queryStore = new BridgeStore<QueryCurrentFloorData>();

export function initializeWidgetBridge() {
  setActiveStore.init();
  queryStore.init();
}

export function subscribeSetActive(listener: () => void): () => void {
  return setActiveStore.subscribe(listener);
}

export function subscribeQuery(listener: () => void): () => void {
  return queryStore.subscribe(listener);
}

export function getSetActiveSnapshot(): WidgetState<SetActiveFloorData> {
  return setActiveStore.getSnapshot();
}

export function getQuerySnapshot(): WidgetState<QueryCurrentFloorData> {
  return queryStore.getSnapshot();
}
