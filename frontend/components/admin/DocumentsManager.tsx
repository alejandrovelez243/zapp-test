"use client";

/**
 * components/admin/DocumentsManager.tsx
 *
 * Admin document-management island.  Entirely client-side: state, fetching,
 * and mutations live here.  The RSC shell (app/admin/page.tsx) renders this
 * as a leaf.
 *
 * Structure
 * ─────────
 *   If no admin token is stored → AdminTokenForm (prompt for token)
 *   Else                        → DocumentsPanel
 *     ├─ UploadSection (POST /documents)
 *     ├─ DocumentTable (GET / DELETE / PUT /documents)
 *     └─ StatusAnnouncer (aria-live region for screen readers)
 *
 * Auth pattern (req faq-rag-002):
 *   Token is stored in component state AND in sessionStorage so it survives
 *   page refreshes in the same tab.  It is NEVER exposed in a NEXT_PUBLIC_*
 *   variable.  On 401/403, the stored token is cleared and the form re-shows.
 *
 * API calls use /api/documents (same-origin via Next.js rewrite → FastAPI).
 * Each call sends "X-Admin-Token: <token>".
 *
 * Visual character: matches the classical, typographically-led aesthetic of
 * the chat surface — serif headings, muted ink-on-paper palette, aubergine
 * accent, hairline rules, generous whitespace.
 *
 * Accessibility: WCAG AA; aria-live for list/status changes; keyboard-operable
 * controls; visible focus rings; confirm state on destructive delete (two-step,
 * keyboard escapable).
 *
 * No analytics SDK is imported or used.  req frontend-shell-022.
 *
 * Traces: faq-rag-001, faq-rag-002, faq-rag-006, faq-rag-007, faq-rag-008
 */

import * as React from "react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import {
  listDocuments,
  uploadDocument,
  deleteDocument,
  replaceDocument,
  isAdminApiError,
  type DocumentSummary,
} from "@/lib/adminApi";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const SESSION_KEY = "admin_token";
const ACCEPTED_TYPES = ".pdf,.md,.txt";
const CONFIRM_TIMEOUT_MS = 4000;

// ---------------------------------------------------------------------------
// Utility: derive badge variant from ingestion status
// ---------------------------------------------------------------------------

type BadgeVariant = "default" | "secondary" | "outline" | "destructive";

function statusVariant(status: string): BadgeVariant {
  switch (status) {
    case "ready":
      return "default";       // aubergine — success
    case "ingesting":
      return "secondary";     // warm grey — in-progress
    case "pending":
      return "outline";       // neutral border — waiting
    case "failed":
      return "destructive";   // muted terracotta — error
    default:
      return "outline";
  }
}

/** Human-readable status label. */
function statusLabel(status: string): string {
  switch (status) {
    case "ready":
      return "ready";
    case "ingesting":
      return "ingesting…";
    case "pending":
      return "pending";
    case "failed":
      return "failed";
    default:
      return status;
  }
}

// ---------------------------------------------------------------------------
// Shared input style — mirrors the Textarea component's border/focus tokens
// ---------------------------------------------------------------------------

const inputClass =
  "w-full rounded-lg border border-input bg-transparent px-2.5 py-2 text-sm " +
  "outline-none transition-colors placeholder:text-muted-foreground " +
  "focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 " +
  "disabled:cursor-not-allowed disabled:opacity-50";

// ---------------------------------------------------------------------------
// AdminTokenForm — prompts for the admin token
// ---------------------------------------------------------------------------

interface AdminTokenFormProps {
  onToken: (token: string) => void;
  error?: string | null;
}

function AdminTokenForm({ onToken, error }: AdminTokenFormProps) {
  const [value, setValue] = React.useState("");
  const inputId = React.useId();

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = value.trim();
    if (!trimmed) return;
    onToken(trimmed);
  }

  return (
    <div className="flex flex-col items-center justify-center min-h-[40vh] px-4">
      <div className="w-full max-w-sm">
        <h2 className="font-heading text-2xl text-foreground mb-1 leading-tight">
          Admin access
        </h2>
        <p className="text-sm text-muted-foreground mb-6">
          Enter your admin token to manage course documents.
        </p>

        <form onSubmit={handleSubmit} className="flex flex-col gap-4" noValidate>
          <div className="flex flex-col gap-1.5">
            <label
              htmlFor={inputId}
              className="text-xs font-semibold tracking-widest uppercase text-muted-foreground select-none"
            >
              Admin token
            </label>
            <input
              id={inputId}
              type="password"
              autoComplete="current-password"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              placeholder="Enter token…"
              className={inputClass}
              aria-describedby={error ? `${inputId}-error` : undefined}
              aria-invalid={!!error}
            />
            {error && (
              <p
                id={`${inputId}-error`}
                className="text-xs text-destructive mt-0.5"
                role="alert"
              >
                {error}
              </p>
            )}
          </div>

          <Button
            type="submit"
            disabled={!value.trim()}
            className="self-start"
          >
            Continue
          </Button>
        </form>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// UploadSection — file picker → POST /documents
// ---------------------------------------------------------------------------

interface UploadSectionProps {
  token: string;
  onUploadComplete: () => void;
  onAuthError: () => void;
}

function UploadSection({ token, onUploadComplete, onAuthError }: UploadSectionProps) {
  const [file, setFile] = React.useState<File | null>(null);
  const [status, setStatus] = React.useState<
    "idle" | "uploading" | "success" | "error"
  >("idle");
  const [message, setMessage] = React.useState<string | null>(null);
  const fileInputId = React.useId();
  const fileInputRef = React.useRef<HTMLInputElement>(null);

  async function handleUpload(e: React.FormEvent) {
    e.preventDefault();
    if (!file || status === "uploading") return;
    setStatus("uploading");
    setMessage(null);

    const result = await uploadDocument(token, file);

    if (isAdminApiError(result)) {
      if (result.kind === "auth") {
        onAuthError();
        return;
      }
      setStatus("error");
      setMessage(result.message);
      return;
    }

    setStatus("success");
    setMessage(`Scheduled for ingestion (id: ${result.id})`);
    setFile(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
    onUploadComplete();
  }

  return (
    <section aria-labelledby="upload-heading" className="mb-8">
      <h3
        id="upload-heading"
        className="font-heading text-lg text-foreground mb-1 leading-tight"
      >
        Upload document
      </h3>
      <p className="text-xs text-muted-foreground mb-4">
        Accepted formats: PDF, Markdown, plain text. Ingestion runs as a
        background job — status updates in the list below.
      </p>

      <form onSubmit={handleUpload} className="flex flex-col gap-3" noValidate>
        <div className="flex flex-col gap-1.5">
          <label
            htmlFor={fileInputId}
            className="text-xs font-semibold tracking-widest uppercase text-muted-foreground select-none"
          >
            File
          </label>
          <input
            ref={fileInputRef}
            id={fileInputId}
            type="file"
            accept={ACCEPTED_TYPES}
            onChange={(e) => {
              setFile(e.target.files?.[0] ?? null);
              setStatus("idle");
              setMessage(null);
            }}
            className={cn(
              inputClass,
              // File input needs extra styling so the native button looks correct
              "file:border-0 file:bg-transparent file:text-sm file:font-medium file:text-foreground file:cursor-pointer cursor-pointer py-1.5"
            )}
          />
        </div>

        <div className="flex items-center gap-3 flex-wrap">
          <Button
            type="submit"
            disabled={!file || status === "uploading"}
            size="sm"
          >
            {status === "uploading" ? "Uploading…" : "Upload"}
          </Button>

          {message && (
            <p
              className={cn(
                "text-xs",
                status === "success"
                  ? "text-muted-foreground"
                  : "text-destructive"
              )}
              role={status === "error" ? "alert" : undefined}
            >
              {message}
            </p>
          )}
        </div>
      </form>
    </section>
  );
}

// ---------------------------------------------------------------------------
// ReplaceControl — inline hidden file input to trigger PUT /documents/{id}
// ---------------------------------------------------------------------------

interface ReplaceControlProps {
  token: string;
  doc: DocumentSummary;
  onComplete: () => void;
  onAuthError: () => void;
  onAnnounce: (msg: string) => void;
}

function ReplaceControl({
  token,
  doc,
  onComplete,
  onAuthError,
  onAnnounce,
}: ReplaceControlProps) {
  const [busy, setBusy] = React.useState(false);
  const inputRef = React.useRef<HTMLInputElement>(null);

  async function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setBusy(true);

    const result = await replaceDocument(token, doc.id, file);

    if (inputRef.current) inputRef.current.value = "";
    setBusy(false);

    if (isAdminApiError(result)) {
      if (result.kind === "auth") {
        onAuthError();
        return;
      }
      onAnnounce(`Replace failed: ${result.message}`);
      return;
    }

    onAnnounce(`"${doc.name}" is being re-ingested (id: ${result.id})`);
    onComplete();
  }

  return (
    <>
      {/* Hidden file input — triggered by the visible button below */}
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPTED_TYPES}
        aria-label={`Replace ${doc.name}`}
        onChange={handleChange}
        className="sr-only"
        tabIndex={-1}
      />
      <Button
        type="button"
        variant="outline"
        size="xs"
        disabled={busy}
        onClick={() => inputRef.current?.click()}
        aria-label={`Replace document: ${doc.name}`}
      >
        {busy ? "Replacing…" : "Replace"}
      </Button>
    </>
  );
}

// ---------------------------------------------------------------------------
// DocumentRow — one row in the document table
// ---------------------------------------------------------------------------

interface DocumentRowProps {
  doc: DocumentSummary;
  token: string;
  confirmingDeleteId: number | null;
  deletingId: number | null;
  onDeleteRequest: (id: number) => void;
  onDeleteConfirm: (id: number) => void;
  onDeleteCancel: () => void;
  onReplaceComplete: () => void;
  onAuthError: () => void;
  onAnnounce: (msg: string) => void;
}

function DocumentRow({
  doc,
  token,
  confirmingDeleteId,
  deletingId,
  onDeleteRequest,
  onDeleteConfirm,
  onDeleteCancel,
  onReplaceComplete,
  onAuthError,
  onAnnounce,
}: DocumentRowProps) {
  const isConfirming = confirmingDeleteId === doc.id;
  const isDeleting = deletingId === doc.id;

  // Keyboard: Escape cancels the confirm state
  function handleDeleteKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Escape" && isConfirming) {
      e.preventDefault();
      onDeleteCancel();
    }
  }

  return (
    <tr className="border-t border-border">
      {/* id — monospace, muted */}
      <td className="py-3 pr-4 font-mono text-xs text-muted-foreground align-middle whitespace-nowrap">
        {doc.id}
      </td>

      {/* name — truncated with title for full text on hover */}
      <td
        className="py-3 pr-6 text-sm text-foreground align-middle max-w-[18ch] truncate"
        title={doc.name}
      >
        {doc.name}
      </td>

      {/* status badge */}
      <td className="py-3 pr-6 align-middle whitespace-nowrap">
        <Badge variant={statusVariant(doc.status)}>
          {statusLabel(doc.status)}
        </Badge>
      </td>

      {/* actions */}
      <td className="py-3 align-middle">
        <div
          className="flex items-center gap-2 flex-wrap"
          onKeyDown={handleDeleteKeyDown}
        >
          {/* Replace — PUT /documents/{id} */}
          <ReplaceControl
            token={token}
            doc={doc}
            onComplete={onReplaceComplete}
            onAuthError={onAuthError}
            onAnnounce={onAnnounce}
          />

          {/* Delete — two-step confirm pattern */}
          {isConfirming ? (
            <>
              <Button
                type="button"
                variant="destructive"
                size="xs"
                disabled={isDeleting}
                onClick={() => onDeleteConfirm(doc.id)}
                aria-label={`Confirm delete ${doc.name}`}
                autoFocus
              >
                {isDeleting ? "Deleting…" : "Confirm?"}
              </Button>
              <button
                type="button"
                className="text-xs text-muted-foreground underline underline-offset-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded"
                onClick={onDeleteCancel}
                aria-label="Cancel delete"
              >
                Cancel
              </button>
            </>
          ) : (
            <Button
              type="button"
              variant="ghost"
              size="xs"
              disabled={isDeleting}
              onClick={() => onDeleteRequest(doc.id)}
              aria-label={`Delete document: ${doc.name}`}
              className="text-muted-foreground hover:text-foreground"
            >
              Delete
            </Button>
          )}
        </div>
      </td>
    </tr>
  );
}

// ---------------------------------------------------------------------------
// DocumentTable — renders the list and handles mutations
// ---------------------------------------------------------------------------

interface DocumentTableProps {
  docs: DocumentSummary[];
  token: string;
  isLoading: boolean;
  listError: string | null;
  onRefresh: () => void;
  onMutated: () => void;
  onAuthError: () => void;
  onAnnounce: (msg: string) => void;
}

function DocumentTable({
  docs,
  token,
  isLoading,
  listError,
  onRefresh,
  onMutated,
  onAuthError,
  onAnnounce,
}: DocumentTableProps) {
  const [confirmingDeleteId, setConfirmingDeleteId] = React.useState<
    number | null
  >(null);
  const [deletingId, setDeletingId] = React.useState<number | null>(null);

  // Auto-cancel confirm state after CONFIRM_TIMEOUT_MS
  React.useEffect(() => {
    if (confirmingDeleteId === null) return;
    const t = setTimeout(() => setConfirmingDeleteId(null), CONFIRM_TIMEOUT_MS);
    return () => clearTimeout(t);
  }, [confirmingDeleteId]);

  async function handleDeleteConfirm(id: number) {
    setDeletingId(id);
    const result = await deleteDocument(token, id);
    setDeletingId(null);
    setConfirmingDeleteId(null);

    if (isAdminApiError(result)) {
      if (result.kind === "auth") {
        onAuthError();
        return;
      }
      onAnnounce(`Delete failed: ${result.message}`);
      return;
    }

    onAnnounce("Document deleted.");
    onMutated();
  }

  return (
    <section aria-labelledby="docs-heading">
      <div className="flex items-baseline justify-between mb-3 gap-2 flex-wrap">
        <h3
          id="docs-heading"
          className="font-heading text-lg text-foreground leading-tight"
        >
          Documents
        </h3>
        <Button
          type="button"
          variant="ghost"
          size="xs"
          onClick={onRefresh}
          disabled={isLoading}
          aria-label="Refresh document list"
          className="text-muted-foreground"
        >
          {isLoading ? "Loading…" : "Refresh"}
        </Button>
      </div>

      {listError && (
        <p className="text-xs text-destructive mb-3" role="alert">
          {listError}
        </p>
      )}

      {docs.length === 0 && !isLoading && !listError ? (
        <p className="text-sm text-muted-foreground italic py-4">
          No documents uploaded yet.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left min-w-[32rem]">
            <thead>
              <tr>
                <th className="pb-2 text-xs font-semibold tracking-widest uppercase text-muted-foreground pr-4">
                  ID
                </th>
                <th className="pb-2 text-xs font-semibold tracking-widest uppercase text-muted-foreground pr-6">
                  Name
                </th>
                <th className="pb-2 text-xs font-semibold tracking-widest uppercase text-muted-foreground pr-6">
                  Status
                </th>
                <th className="pb-2 text-xs font-semibold tracking-widest uppercase text-muted-foreground">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody>
              {docs.map((doc) => (
                <DocumentRow
                  key={doc.id}
                  doc={doc}
                  token={token}
                  confirmingDeleteId={confirmingDeleteId}
                  deletingId={deletingId}
                  onDeleteRequest={(id) => setConfirmingDeleteId(id)}
                  onDeleteConfirm={handleDeleteConfirm}
                  onDeleteCancel={() => setConfirmingDeleteId(null)}
                  onReplaceComplete={onMutated}
                  onAuthError={onAuthError}
                  onAnnounce={onAnnounce}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// DocumentsPanel — the authenticated management view
// ---------------------------------------------------------------------------

interface DocumentsPanelProps {
  token: string;
  onSignOut: () => void;
}

function DocumentsPanel({ token, onSignOut }: DocumentsPanelProps) {
  const [docs, setDocs] = React.useState<DocumentSummary[]>([]);
  const [isLoading, setIsLoading] = React.useState(true);
  const [listError, setListError] = React.useState<string | null>(null);
  // aria-live region content for screen-reader announcements
  const [announcement, setAnnouncement] = React.useState("");

  function announce(msg: string) {
    // Briefly clear then set so repeated identical messages re-trigger aria-live
    setAnnouncement("");
    setTimeout(() => setAnnouncement(msg), 50);
  }

  async function fetchDocs() {
    setIsLoading(true);
    setListError(null);
    const result = await listDocuments(token);
    setIsLoading(false);

    if (isAdminApiError(result)) {
      if (result.kind === "auth") {
        onSignOut();
        return;
      }
      setListError(result.message);
      return;
    }

    setDocs(result);
  }

  // Initial load — data-fetching in useEffect is the standard React pattern;
  // setState calls happen asynchronously inside the async function.
  React.useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void fetchDocs();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  return (
    <div className="w-full">
      {/* aria-live region — announces status changes to assistive technology */}
      <p
        aria-live="polite"
        aria-atomic="true"
        className="sr-only"
      >
        {announcement}
      </p>

      {/* Sign-out affordance */}
      <div className="flex justify-end mb-6">
        <button
          type="button"
          onClick={onSignOut}
          className="text-xs text-muted-foreground underline underline-offset-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded hover:text-foreground transition-colors"
          aria-label="Sign out of admin"
        >
          Sign out
        </button>
      </div>

      {/* Hairline divider */}
      <div className="rule-meander mb-8" aria-hidden="true" />

      <UploadSection
        token={token}
        onUploadComplete={() => void fetchDocs()}
        onAuthError={onSignOut}
      />

      {/* Section divider */}
      <div className="border-t border-border mb-8" aria-hidden="true" />

      <DocumentTable
        docs={docs}
        token={token}
        isLoading={isLoading}
        listError={listError}
        onRefresh={() => void fetchDocs()}
        onMutated={() => void fetchDocs()}
        onAuthError={onSignOut}
        onAnnounce={announce}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// DocumentsManager — root export, manages token lifecycle
// ---------------------------------------------------------------------------

/**
 * DocumentsManager — the admin document management client island.
 *
 * Token lifecycle:
 *   1. On mount: restore token from sessionStorage (if present).
 *   2. On successful token entry: persist to sessionStorage + component state.
 *   3. On 401/403 or sign-out: clear sessionStorage + component state → show form.
 *
 * The token is never stored in a NEXT_PUBLIC_* variable (which would embed it
 * in the JS bundle at build time).
 */
export function DocumentsManager() {
  const [token, setToken] = React.useState<string | null>(null);
  const [tokenError, setTokenError] = React.useState<string | null>(null);
  // Track hydration to avoid sessionStorage access on server
  const [hydrated, setHydrated] = React.useState(false);

  // Restore token from sessionStorage after mount (client-only).
  // setHydrated and setToken are called synchronously here intentionally —
  // this effect runs once on mount to read a browser-only API (sessionStorage)
  // that is unavailable during SSR.  The pattern is correct; the lint rule
  // is suppressed for this targeted case.
  React.useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setHydrated(true);
    const stored =
      typeof window !== "undefined"
        ? sessionStorage.getItem(SESSION_KEY)
        : null;
    if (stored) setToken(stored);
  }, []);

  function handleToken(t: string) {
    sessionStorage.setItem(SESSION_KEY, t);
    setToken(t);
    setTokenError(null);
  }

  function handleSignOut() {
    sessionStorage.removeItem(SESSION_KEY);
    setToken(null);
    setTokenError("Token invalid or expired — please try again.");
  }

  // Avoid a flash of the form while hydrating (token restores asynchronously)
  if (!hydrated) return null;

  if (!token) {
    return (
      <AdminTokenForm
        onToken={handleToken}
        error={tokenError}
      />
    );
  }

  return (
    <DocumentsPanel
      token={token}
      onSignOut={handleSignOut}
    />
  );
}
