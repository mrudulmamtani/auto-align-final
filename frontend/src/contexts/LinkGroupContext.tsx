"use client";

import {
  createContext,
  useContext,
  useCallback,
  useRef,
  useSyncExternalStore,
  type ReactNode,
} from "react";

// ── Types ────────────────────────────────────────────────────

export type LinkColor = "amber" | "green" | "blue" | "cyan" | "magenta" | "none";

export interface LinkSelection {
  /** The URN of the selected entity (control, asset, event, etc.) */
  urn: string;
  /** Entity type for filtering */
  type: "control" | "asset" | "event" | "standard" | "requirement" | "case" | "process";
  /** Optional display label */
  label?: string;
  /** Timestamp of the selection */
  ts: number;
}

type Listener = () => void;

// ── Link Group Store (external store for useSyncExternalStore) ──

class LinkGroupStore {
  private selections: Map<LinkColor, LinkSelection | null> = new Map();
  private listeners: Set<Listener> = new Set();

  getSelection(color: LinkColor): LinkSelection | null {
    return this.selections.get(color) ?? null;
  }

  publish(color: LinkColor, selection: LinkSelection): void {
    if (color === "none") return;
    this.selections.set(color, { ...selection, ts: Date.now() });
    this.notify();
  }

  clear(color: LinkColor): void {
    this.selections.delete(color);
    this.notify();
  }

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  private notify(): void {
    for (const l of this.listeners) l();
  }

  getSnapshot(): Map<LinkColor, LinkSelection | null> {
    return this.selections;
  }
}

// ── Context ──────────────────────────────────────────────────

interface LinkGroupContextValue {
  store: LinkGroupStore;
}

const LinkGroupCtx = createContext<LinkGroupContextValue | null>(null);

export function LinkGroupProvider({ children }: { children: ReactNode }) {
  const storeRef = useRef(new LinkGroupStore());

  return (
    <LinkGroupCtx.Provider value={{ store: storeRef.current }}>
      {children}
    </LinkGroupCtx.Provider>
  );
}

// ── Hooks ────────────────────────────────────────────────────

function useLinkGroupStore(): LinkGroupStore {
  const ctx = useContext(LinkGroupCtx);
  if (!ctx) throw new Error("useLinkGroup must be inside LinkGroupProvider");
  return ctx.store;
}

/**
 * Subscribe to a link group color and get the current selection.
 * Re-renders only when the store changes.
 */
export function useLinkGroup(color: LinkColor) {
  const store = useLinkGroupStore();

  const selection = useSyncExternalStore(
    useCallback((cb: Listener) => store.subscribe(cb), [store]),
    () => store.getSelection(color),
    () => null
  );

  const publish = useCallback(
    (sel: Omit<LinkSelection, "ts">) => {
      store.publish(color, { ...sel, ts: Date.now() });
    },
    [store, color]
  );

  const clear = useCallback(() => {
    store.clear(color);
  }, [store, color]);

  return { selection, publish, clear };
}

/**
 * Publish to a link group without subscribing.
 */
export function useLinkGroupPublish() {
  const store = useLinkGroupStore();

  return useCallback(
    (color: LinkColor, sel: Omit<LinkSelection, "ts">) => {
      store.publish(color, { ...sel, ts: Date.now() });
    },
    [store]
  );
}
