/**
 * app/page.tsx
 *
 * Root page — a pure React Server Component.  Renders the `ChatShell` client
 * island which owns all interactive chat state.
 *
 * No analytics SDK, no inline CSS, no scaffold logic.
 * req: frontend-shell-001 (single-column chat surface),
 *      frontend-shell-022 (no analytics/PostHog initialized here).
 */

import { ChatShell } from "@/components/chat/ChatShell";

export default function ChatPage() {
  return <ChatShell />;
}
