/**
 * lib/i18n/pt.ts
 *
 * Portuguese chrome dictionary.
 *
 * Traces: frontend-shell-014, frontend-shell-015
 */

import type { Dict } from "./index";

const pt: Dict = {
  "composer.placeholder": "Faça uma pergunta…",
  "composer.sendLabel": "Enviar",
  "composer.hint": "Enter para enviar · Shift+Enter para nova linha",
  "state.sending": "A pensar…",
  "error.generic": "Algo correu mal. Por favor, tente novamente.",
  "error.network":
    "Erro de rede. Verifique a sua ligação e tente novamente.",
  "lang.indicatorLabel": "Idioma da sessão",
  "lang.lockedHint": "Sessão bloqueada em {lang}",
  "guardrail.filtered": "Esta mensagem foi filtrada.",
  "review.note": "Assinalado para revisão",
  "details.toggle": "Detalhes",
  "details.label.langConfidence": "Confiança linguística",
  "details.label.confidenceScore": "Pontuação de confiança",
  "details.label.detectedCountry": "País detetado",
  "details.label.normalizedText": "Texto normalizado",
  "a11y.transcriptLabel": "Transcrição da conversa",
  "a11y.newReply": "Nova resposta do assistente",
  // Empty-state welcome + suggested starter prompts (usability-001)
  "emptyState.welcome": "Bem-vindo. A vida examinada começa com uma pergunta.",
  "emptyState.promptsLabel": "Perguntas sugeridas",
  "emptyState.prompt1": "Que cursos oferecem?",
  "emptyState.prompt2": "Como me inscrevo num evento?",
  "emptyState.prompt3": "O que é o Estoicismo?",
  "emptyState.prompt4": "Fala-me sobre a filosofia da escola",
};

export default pt;
