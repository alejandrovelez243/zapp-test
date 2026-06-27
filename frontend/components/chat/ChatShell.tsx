"use client";

/**
 * components/chat/ChatShell.tsx
 *
 * The single client island for the chat surface.  All interactive state lives
 * here; the RSC shell (`app/page.tsx`) renders this as a leaf.
 *
 * Responsibilities:
 *   - Calls `useChat()` to obtain `{ turns, status, send, activeLang }`.
 *   - Passes `activeLang` to every child so chrome re-localizes when the
 *     session language changes between turns (req frontend-shell-015).
 *   - Owns autoscroll: scrolls to the bottom when turns grow, but pauses when
 *     the user has manually scrolled up (respects reading context).
 *   - Renders:
 *       ┌──────────────────────────┐
 *       │  header (serif title)    │
 *       │  .rule-meander hairline  │
 *       │  <Transcript>            │  ← grows / scrollable
 *       │  <Composer>              │  ← pinned at bottom
 *       └──────────────────────────┘
 *
 * Visual character: narrow reading measure (~66ch), generous whitespace,
 * classical serif heading, warm paper background.  req frontend-shell-017.
 *
 * No analytics SDK is imported or called here.  req frontend-shell-022.
 *
 * Traces: frontend-shell-001, frontend-shell-015, frontend-shell-022
 */

import { useEffect, useRef, useCallback } from "react";

import { useChat } from "@/lib/hooks/useChat";
import { Transcript } from "./Transcript";
import { Composer } from "./Composer";

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * ChatShell — the root interactive island.
 *
 * Mounted once on `page.tsx`.  Renders the full chat surface including the
 * classical editorial header, the scrollable transcript, and the composer.
 * Every chrome string is keyed through `t(activeLang, …)` inside the child
 * components, so any `active_lang` change from the hook propagates instantly.
 */
export function ChatShell() {
  const { turns, status, send, activeLang } = useChat();

  // ── Autoscroll ─────────────────────────────────────────────────────────────
  // We keep a ref to the scroll container and a boolean ref that tracks whether
  // the user has manually scrolled up.  When `turns` grows we scroll to bottom
  // only if the user hasn't panned away from the end.

  const scrollRef = useRef<HTMLDivElement>(null);
  /** True once the user has scrolled up; cleared when they return to the bottom. */
  const userScrolledUp = useRef(false);

  // Detect manual upward scroll.
  const handleScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    // If the user is more than 80px from the bottom, treat as "scrolled up".
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    userScrolledUp.current = distanceFromBottom > 80;
  }, []);

  // Scroll to bottom whenever turns are appended (if not paused).
  useEffect(() => {
    if (userScrolledUp.current) return;
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [turns]);

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    /*
     * Full-height single-column column.  The outer div fills the viewport
     * height established by <body> in globals.css (min-h-full flex flex-col).
     * The inner wrapper is centered and max-width ~66ch for a readable measure.
     * req frontend-shell-001: single-column chat surface.
     */
    <div className="flex flex-col flex-1 min-h-0 bg-background text-foreground">
      {/*
       * Centered content column: max-w matches the --width-measure CSS token
       * (~66ch) for a classical reading measure.  Horizontal padding gives
       * generous margins on wider viewports.
       */}
      <div className="flex flex-col flex-1 min-h-0 w-full max-w-[66ch] mx-auto px-4 sm:px-6 lg:px-8 py-8">

        {/* ── Editorial header ─────────────────────────────────────────── */}
        <header className="mb-6 shrink-0">
          {/*
           * Display serif heading — Newsreader (--font-serif) applied globally
           * to h1..h6 via the @layer base rule in globals.css.
           * Large, well-set type is the primary design element; no decorative
           * gradient or background.  req frontend-shell-017.
           */}
          <h1 className="font-heading text-3xl tracking-tight text-foreground leading-none mb-1">
            Philosophy School
          </h1>
          {/*
           * Sub-caption in humanist sans, quiet muted colour, sets the tone
           * before the first message arrives.
           */}
          <p className="text-sm text-muted-foreground mt-2 font-sans">
            Ask a question. The school is listening.
          </p>

          {/*
           * Greek-key meander hairline rule — the classical nod.
           * Sits directly below the title, above the transcript.
           * req frontend-shell-017.
           */}
          <div className="rule-meander mt-5" aria-hidden="true" />
        </header>

        {/* ── Scrollable transcript ─────────────────────────────────────── */}
        {/*
         * `flex-1 min-h-0` allows this area to grow and scroll within the
         * flex column.  `overflow-y-auto` enables vertical scrolling.
         * The scroll container ref feeds the autoscroll logic above.
         */}
        <div
          ref={scrollRef}
          onScroll={handleScroll}
          className="flex-1 min-h-0 overflow-y-auto pb-4"
        >
          {/*
           * If no turns yet, render a calm invitation so the surface is never
           * blank — a considered, literary placeholder.
           */}
          {turns.length === 0 ? (
            <p className="text-muted-foreground text-sm italic mt-8 text-center select-none">
              Begin your inquiry below.
            </p>
          ) : (
            /*
             * Transcript: aria-live log; passes activeLang so every
             * ContractMeta component localizes to the session language.
             * req frontend-shell-001, frontend-shell-015, frontend-shell-019.
             */
            <Transcript turns={turns} activeLang={activeLang} />
          )}
        </div>

        {/* ── Composer ──────────────────────────────────────────────────── */}
        {/*
         * Pinned at the bottom of the column, never scrolls away.
         * Passes `activeLang` so all chrome copy (placeholder, send label,
         * hint) re-renders when the session language changes (req 015).
         * req frontend-shell-001, frontend-shell-005, frontend-shell-007.
         */}
        <div className="shrink-0 pt-4 border-t border-border">
          <Composer
            onSend={send}
            status={status}
            activeLang={activeLang}
          />
        </div>
      </div>
    </div>
  );
}
