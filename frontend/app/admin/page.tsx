/**
 * app/admin/page.tsx
 *
 * Admin document-management page.  A pure React Server Component — renders the
 * `DocumentsManager` client island which owns all interactive state.
 *
 * Accessible at /admin.  The admin token gate lives entirely in the client
 * island: the RSC has no knowledge of the token and no server-side auth logic,
 * consistent with the frontend-only auth pattern specified in the design.
 *
 * Visual character: matches the classical aesthetic of the main chat surface —
 * the same header / meander-rule pattern from ChatShell, editorial typography,
 * ink-on-paper palette, generous whitespace.
 *
 * No analytics SDK, no NEXT_PUBLIC_* secrets.  req frontend-shell-022.
 *
 * Traces: faq-rag-001, faq-rag-002, faq-rag-006, faq-rag-007, faq-rag-008
 */

import Link from "next/link";
import { AdminConsole } from "@/components/admin/AdminConsole";

export const metadata = {
  title: "Documents — Admin | Philosophy School",
  description: "Upload, review, and manage course documents for the FAQ corpus.",
};

export default function AdminDocumentsPage() {
  return (
    <main className="flex flex-col flex-1 min-h-0 bg-background text-foreground">
      {/*
       * Centred content column — same max-width and horizontal padding as the
       * chat surface so the two pages feel like a coherent product.
       */}
      <div className="flex flex-col flex-1 min-h-0 w-full max-w-[72ch] mx-auto px-4 sm:px-6 lg:px-8 py-8">

        {/* ── Editorial header ────────────────────────────────────────── */}
        <header className="mb-6 shrink-0">
          <h1 className="font-heading text-3xl tracking-tight text-foreground leading-none mb-1">
            Document corpus
          </h1>
          <p className="text-sm text-muted-foreground mt-2 font-sans">
            Manage the documents that ground the school&rsquo;s FAQ responses.
          </p>
          {/*
           * Sub-navigation link back to the chat surface — a quiet text link,
           * not a button, consistent with the editorial character.
           */}
          <Link
            href="/"
            className="inline-block mt-3 text-xs text-primary underline underline-offset-2 hover:opacity-70 transition-opacity focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded"
          >
            ← Back to chat
          </Link>

          {/* Greek-key meander hairline rule */}
          <div className="rule-meander mt-5" aria-hidden="true" />
        </header>

        {/* ── AdminConsole client island ───────────────────────────────── */}
        {/*
         * AdminConsole owns the token gate vs. console state machine,
         * the Toaster, DeleteConfirm, and all document-management UI.
         * task 9 / req admin-console-001 … admin-console-005
         */}
        <div className="flex-1">
          <AdminConsole />
        </div>
      </div>
    </main>
  );
}
