/**
 * vitest.setup.ts
 *
 * Loaded by vitest before every test suite (see vitest.config.ts setupFiles).
 * 1. Registers @testing-library/jest-dom custom matchers.
 * 2. Polyfills browser APIs that jsdom omits but base-ui / shadcn need.
 */

import "@testing-library/jest-dom";

// ── Polyfills for jsdom ─────────────────────────────────────────────────────

// ResizeObserver — used by base-ui layout calculations.
if (typeof global.ResizeObserver === "undefined") {
  global.ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}

// IntersectionObserver — may be used by tooltip/popover positioning.
if (typeof global.IntersectionObserver === "undefined") {
  global.IntersectionObserver = class IntersectionObserver {
    readonly root = null;
    readonly rootMargin = "";
    readonly thresholds: ReadonlyArray<number> = [];
    observe() {}
    unobserve() {}
    disconnect() {}
    takeRecords() { return []; }
  } as unknown as typeof IntersectionObserver;
}

// window.matchMedia — consumed by some media-query hooks.
if (typeof window !== "undefined" && typeof window.matchMedia === "undefined") {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }),
  });
}

// PointerEvent — user-event v14 dispatches pointer events; jsdom needs the class.
if (typeof global.PointerEvent === "undefined") {
  // Minimal shim — only the properties userEvent touches.
  global.PointerEvent = class PointerEvent extends MouseEvent {
    constructor(type: string, params: PointerEventInit = {}) {
      super(type, params);
    }
  } as typeof PointerEvent;
}

// Element.scrollTo — jsdom does not implement scrollTo on elements.
// ChatShell uses el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
// in its autoscroll useEffect; we no-op it so tests don't throw.
if (!HTMLElement.prototype.scrollTo) {
  HTMLElement.prototype.scrollTo = function () {};
}

// window.scrollTo — same reason, guard for any window-level scroll call.
if (!window.scrollTo) {
  window.scrollTo = () => {};
}
