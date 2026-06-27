/**
 * lib/validateFile.ts
 *
 * Shared file-validation helper for admin upload surfaces.
 * Extracted from UploadDropzone and DocumentCard to avoid duplication.
 *
 * Accepted extensions: .pdf · .md · .txt only.
 * Returns null on valid, or a human-readable error string on failure.
 *
 * req: admin-console-007 (reject before any request)
 * req: admin-console-016 (same validation for Replace)
 */

/** Lower-case, dot-prefixed accepted extensions (req admin-console-007). */
export const ACCEPTED_EXTENSIONS = [".pdf", ".md", ".txt"] as const
export type AcceptedExtension = (typeof ACCEPTED_EXTENSIONS)[number]

/** Human-readable joined list for error messages and hints. */
export const ACCEPTED_LABEL = ACCEPTED_EXTENSIONS.join(", ")

/**
 * Extract lower-cased dot-prefixed extension from a filename.
 * Returns empty string when the name has no extension.
 */
export function getExtension(filename: string): string {
  const dotIndex = filename.lastIndexOf(".")
  if (dotIndex === -1) return ""
  return filename.slice(dotIndex).toLowerCase()
}

/**
 * Validate a File against the accepted extension list.
 * Returns null on success, or a human-readable error string on failure.
 * Does NOT call onFile — rejection happens before any request (req admin-console-007).
 */
export function validateFile(file: File): string | null {
  const ext = getExtension(file.name)
  if ((ACCEPTED_EXTENSIONS as readonly string[]).includes(ext)) return null
  return ext
    ? `"${ext}" files are not accepted. Please upload a ${ACCEPTED_LABEL} file.`
    : `Cannot determine file type. Please upload a ${ACCEPTED_LABEL} file.`
}
