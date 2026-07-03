import { useEffect, useMemo, useState } from "react";
import { knownRunEventTypes, openRunEventSource, type RunEvent } from "../api";

export interface UseRunEventsResult {
  connected: boolean;
  error: string | null;
  events: RunEvent[];
}

export function useRunEvents({
  runId,
  enabled = true,
  onEvent
}: {
  runId: string | null | undefined;
  enabled?: boolean;
  onEvent?: (event: RunEvent) => void;
}): UseRunEventsResult {
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);

  useEffect(() => {
    setEvents([]);
    setConnected(false);
    setError(null);

    if (!runId || !enabled) {
      return;
    }

    const source = openRunEventSource(runId);
    const handlers: Array<[string, EventListener]> = [];

    source.onopen = () => {
      setConnected(true);
      setError(null);
    };
    source.onerror = () => {
      setConnected(false);
      setError("Run event stream disconnected.");
    };

    for (const eventType of knownRunEventTypes) {
      const handler = ((message: MessageEvent<string>) => {
        const event = eventFromSse(eventType, message);
        if (!event) {
          return;
        }
        setEvents((current) => mergeEvents([...current, event]));
        onEvent?.(event);
      }) as EventListener;
      source.addEventListener(eventType, handler);
      handlers.push([eventType, handler]);
    }

    return () => {
      for (const [eventType, handler] of handlers) {
        source.removeEventListener(eventType, handler);
      }
      source.onopen = null;
      source.onerror = null;
      source.close();
      setConnected(false);
    };
  }, [enabled, onEvent, runId]);

  return useMemo(() => ({ connected, error, events }), [connected, error, events]);
}

export function eventFromSse(eventType: string, message: MessageEvent<string>): RunEvent | null {
  let payload: Record<string, unknown> = {};
  try {
    const parsed = JSON.parse(message.data) as unknown;
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      payload = parsed as Record<string, unknown>;
    }
  } catch {
    payload = { message: message.data };
  }

  const sequence = Number(message.lastEventId);
  if (!Number.isFinite(sequence)) {
    return null;
  }

  return {
    sequence,
    event_type: eventType,
    payload,
    actor_label: "",
    created_at: new Date().toISOString()
  };
}

function mergeEvents(events: RunEvent[]): RunEvent[] {
  const bySequence = new Map<number, RunEvent>();
  for (const event of events) {
    bySequence.set(event.sequence, event);
  }
  return Array.from(bySequence.values()).sort((a, b) => a.sequence - b.sequence);
}
