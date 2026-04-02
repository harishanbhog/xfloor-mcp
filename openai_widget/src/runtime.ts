import type { QueryCurrentFloorData, SetActiveFloorData } from './types';

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

function readPreviewData(): unknown {
  const node = document.getElementById('widget-preview-data');
  if (!node) return undefined;
  try {
    return JSON.parse(node.textContent || '{}');
  } catch {
    return undefined;
  }
}

export function getWidgetData<T>(): T {
  const preview = readPreviewData();
  if (preview && Object.keys(preview as Record<string, unknown>).length > 0) {
    return preview as T;
  }
  const apiData = window.openai?.toolOutput?.structuredContent;
  return (window.structuredContent || window.__structuredContent || apiData || {}) as T;
}

export function getSetActiveFloorData(): SetActiveFloorData {
  return getWidgetData<SetActiveFloorData>();
}

export function getQueryCurrentFloorData(): QueryCurrentFloorData {
  return getWidgetData<QueryCurrentFloorData>();
}
