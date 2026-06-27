/**
 * lib/i18n/en.ts
 *
 * English chrome dictionary.  This is also the authoritative fallback: every
 * key that is missing from another locale dict will resolve to the value here
 * (see lib/i18n/index.ts).
 *
 * Traces: frontend-shell-014, frontend-shell-016
 */

import type { Dict } from "./index";

const en: Dict = {
  "composer.placeholder": "Ask a question…",
  "composer.sendLabel": "Send",
  "composer.hint": "Enter to send · Shift+Enter for a new line",
  "state.sending": "Thinking…",
  "error.generic": "Something went wrong. Please try again.",
  "error.network":
    "Network error. Please check your connection and try again.",
  "lang.indicatorLabel": "Session language",
  "lang.lockedHint": "Session locked to {lang}",
  "guardrail.filtered": "This message was filtered.",
  "review.note": "Flagged for review",
  "details.toggle": "Details",
  "details.label.langConfidence": "Language confidence",
  "details.label.confidenceScore": "Confidence score",
  "details.label.detectedCountry": "Detected country",
  "details.label.normalizedText": "Normalized text",
  "a11y.transcriptLabel": "Conversation transcript",
  "a11y.newReply": "New reply from the assistant",
};

export default en;
