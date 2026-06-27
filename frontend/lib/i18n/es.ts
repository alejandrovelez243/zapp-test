/**
 * lib/i18n/es.ts
 *
 * Spanish chrome dictionary.
 *
 * Traces: frontend-shell-014, frontend-shell-015
 */

import type { Dict } from "./index";

const es: Dict = {
  "composer.placeholder": "Haz una pregunta…",
  "composer.sendLabel": "Enviar",
  "composer.hint": "Intro para enviar · Shift+Intro para nueva línea",
  "state.sending": "Pensando…",
  "error.generic": "Algo salió mal. Por favor, inténtalo de nuevo.",
  "error.network":
    "Error de red. Comprueba tu conexión e inténtalo de nuevo.",
  "lang.indicatorLabel": "Idioma de la sesión",
  "lang.lockedHint": "Sesión fijada a {lang}",
  "guardrail.filtered": "Este mensaje fue filtrado.",
  "review.note": "Marcado para revisión",
  "details.toggle": "Detalles",
  "details.label.langConfidence": "Confianza lingüística",
  "details.label.confidenceScore": "Puntuación de confianza",
  "details.label.detectedCountry": "País detectado",
  "details.label.normalizedText": "Texto normalizado",
  "a11y.transcriptLabel": "Transcripción de la conversación",
  "a11y.newReply": "Nueva respuesta del asistente",
};

export default es;
