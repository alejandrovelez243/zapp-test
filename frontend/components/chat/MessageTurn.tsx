/**
 * components/chat/MessageTurn.tsx
 *
 * Renders a single ChatTurn in one of three visual variants:
 *
 *   student   — sans-serif, muted foreground, with a small localised speaker
 *               label ("You" / "Tú" / "Você").  Visually quiet; the assistant
 *               voice is the primary typographic presence on the page.
 *
 *   assistant — Newsreader serif (font-heading), full ink foreground,
 *               generous line-height.  A screen-reader-only span carries the
 *               `a11y.newReply` announcement inside the outer aria-live region
 *               (req frontend-shell-019).  A clearly-marked ContractMeta slot
 *               below the reply text is reserved for task 10.
 *
 *   error     — sans-serif, italic, muted foreground — calm and non-alarming
 *               (req frontend-shell-006).
 *
 * Visual philosophy: editorial and typographic, never chat-bubbly.  No speech
 * bubbles, no per-turn colored backgrounds.  Hierarchy is expressed through
 * font choice, size, and weight alone — consistent with the classical,
 * ink-on-paper aesthetic (req frontend-shell-017).
 *
 * Presentational: no client-side state or browser APIs are required.
 *
 * Traces: frontend-shell-001, frontend-shell-004, frontend-shell-019
 */

import type { ChatTurn } from "@/lib/contract";
import { t } from "@/lib/i18n";
import { LangIndicator } from "./contract/LangIndicator";
import { DetectedLangHint } from "./contract/DetectedLangHint";
import { ReviewMarker } from "./contract/ReviewMarker";
import { GuardrailNote } from "./contract/GuardrailNote";
import { DetailsDisclosure } from "./contract/DetailsDisclosure";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface MessageTurnProps {
  /** The turn to render. */
  turn: ChatTurn;
  /**
   * ISO 639-1 code from the per-turn contract's `active_lang` field.
   * Used to localise the student speaker label and the sr-only announcement.
   */
  activeLang: string;
}

// ---------------------------------------------------------------------------
// Speaker label (inline map — too short to warrant an i18n key)
// ---------------------------------------------------------------------------

/**
 * Very short speaker pronoun in the three supported languages.
 * Falls back to "You" for any `activeLang` outside the supported set
 * (req frontend-shell-016).
 */
const STUDENT_LABEL: Readonly<Record<string, string>> = {
  en: "You",
  es: "Tú",
  pt: "Você",
} as const;

// ---------------------------------------------------------------------------
// Private sub-components
// ---------------------------------------------------------------------------

/**
 * StudentTurn — the student's message in a quiet, muted typographic register.
 *
 * Visually secondary to the assistant voice: smaller, sans-serif, warm grey.
 * A hairline top-border separates each turn from the one above it.
 */
function StudentTurn({
  text,
  activeLang,
}: {
  text: string;
  activeLang: string;
}) {
  const label = STUDENT_LABEL[activeLang] ?? "You";
  return (
    <article className="border-t border-border pt-5 pb-4">
      {/*
       * Speaker label: small-caps, wide tracking, muted — typographic signal
       * only.  aria-hidden because the label is decorative; the message text
       * conveys the full content to assistive technology.
       */}
      <p
        aria-hidden="true"
        className="font-sans text-[0.6rem] font-semibold tracking-[0.16em] uppercase text-muted-foreground mb-2 select-none leading-none"
      >
        {label}
      </p>

      {/* Message body: sans-serif, warm grey — subordinate register */}
      <p className="font-sans text-sm text-muted-foreground leading-relaxed whitespace-pre-wrap">
        {text}
      </p>
    </article>
  );
}

/**
 * AssistantTurn — the philosophical voice of the platform.
 *
 * Rendered in Newsreader (font-heading) at full ink foreground: the dominant
 * typographic element on the page, carrying the scholarly reply.
 *
 * A screen-reader-only span announces the arrival of a new reply to
 * assistive technology when this element is inserted into the outer
 * role="log" aria-live="polite" region (req frontend-shell-019).
 *
 * The ContractMeta slot below the reply text is reserved for task 10.
 */
function AssistantTurn({
  turn,
  activeLang,
}: {
  turn: Extract<ChatTurn, { role: "assistant" }>;
  activeLang: string;
}) {
  return (
    <article className="border-t border-border pt-7 pb-7">
      {/*
       * Screen-reader announcement — req frontend-shell-019.
       *
       * When this <article> is inserted into the parent Transcript's
       * role="log" / aria-live="polite" container, assistive technology
       * reads this sr-only span first, announcing "New reply from the
       * assistant" (or the localised equivalent) before the reply body.
       * The span is visually hidden via Tailwind's `sr-only` utility.
       */}
      <span className="sr-only">{t(activeLang, "a11y.newReply")}</span>

      {/*
       * Reply body — req frontend-shell-004.
       *
       * Newsreader serif (font-heading), full ink foreground, relaxed
       * line-height for comfortable long-form reading.  max-w-prose caps
       * the reading measure to ~65 ch (design spec targets ~66 ch).
       * whitespace-pre-wrap preserves any intentional line breaks in the
       * reply without allowing unconstrained text overflow.
       */}
      <p className="font-heading text-foreground text-base leading-relaxed max-w-prose whitespace-pre-wrap">
        {turn.contract.reply}
      </p>

      {/*
       * ── ContractMeta ──────────────────────────────────────────────────
       *
       * Inline row of discreet per-turn signals: active language, session-lock
       * hint (when detected_lang ≠ active_lang), review marker (when
       * needs_review=true), and guardrail note (when guardrails fired).
       *
       * req 008 — ReviewMarker: hairline side-rule + tooltip, no red banner
       * req 009 — LangIndicator: discreet active_lang indicator
       * req 010 — DetectedLangHint: quiet "session locked" hint on mismatch
       * req 011 — GuardrailNote: calm "filtered" copy, no raw internals
       * ──────────────────────────────────────────────────────────────────
       */}
      <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1">
        {/* req 009 — always rendered; discreet and non-intrusive */}
        <LangIndicator
          activeLang={turn.contract.active_lang}
          lang={activeLang}
        />
        {/* req 010 — renders only when detected_lang ≠ active_lang */}
        <DetectedLangHint
          detectedLang={turn.contract.detected_lang}
          activeLang={turn.contract.active_lang}
          lang={activeLang}
        />
        {/* req 008 — renders only when needs_review=true; no red/alarm */}
        <ReviewMarker
          needsReview={turn.contract.needs_review}
          lang={activeLang}
        />
        {/* req 011 — renders only when guardrails.input/output non-empty */}
        <GuardrailNote
          guardrails={turn.contract.guardrails}
          lang={activeLang}
        />
      </div>

      {/*
       * req 012/013 — DetailsDisclosure: renders the collapsible when the
       * NEXT_PUBLIC_SHOW_DETAILS flag is on; returns null otherwise so the
       * four debug fields (lang_confidence, confidence_score,
       * final_normalized_text, detected_country) are never exposed to students.
       */}
      <DetailsDisclosure contract={turn.contract} lang={activeLang} />
    </article>
  );
}

/**
 * ErrorTurn — a calm, localized error affordance.
 *
 * Italic and muted — never alarming (design spec: "never an error wall").
 * The text is already localised by useChat before it arrives here
 * (req frontend-shell-006).
 */
function ErrorTurn({ text }: { text: string }) {
  return (
    <article className="border-t border-border pt-5 pb-4">
      <p className="font-sans text-sm text-muted-foreground italic leading-relaxed">
        {text}
      </p>
    </article>
  );
}

// ---------------------------------------------------------------------------
// Main export
// ---------------------------------------------------------------------------

/**
 * MessageTurn — dispatches to the correct visual variant for each ChatTurn role.
 *
 * Purely presentational: no client-side state, no browser APIs.
 */
export function MessageTurn({ turn, activeLang }: MessageTurnProps) {
  if (turn.role === "student") {
    return <StudentTurn text={turn.text} activeLang={activeLang} />;
  }

  if (turn.role === "error") {
    return <ErrorTurn text={turn.text} />;
  }

  // role === "assistant" — narrowed by exhaustion above
  return <AssistantTurn turn={turn} activeLang={activeLang} />;
}
