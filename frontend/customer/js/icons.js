/**
 * Hand-authored inline SVG icons (ux-spec §9).
 *
 * All 24px viewBox, drawn with `currentColor` so colour comes from CSS tokens.
 * No icon font, no external files, no third-party brand assets — which also
 * keeps the app fully offline-capable.
 *
 * These are markup constants, not user-facing strings, so they live here rather
 * than in strings.js. Every icon is decorative: views set an accessible name on
 * the control, and the SVG itself is hidden from assistive technology.
 */

const svg = (paths, { width = 24, height = 24 } = {}) =>
  `<svg viewBox="0 0 24 24" width="${width}" height="${height}" fill="none" ` +
  `stroke="currentColor" stroke-width="2" stroke-linecap="round" ` +
  `stroke-linejoin="round" aria-hidden="true" focusable="false">${paths}</svg>`;

export const icons = {
  send: svg('<path d="M3 20.5 21 12 3 3.5l4 8.5-4 8.5Z"/><path d="M7 12h14"/>', {
    width: 20,
    height: 20,
  }),

  mic: svg(
    '<rect x="9" y="2" width="6" height="11" rx="3"/>' +
      '<path d="M5 11a7 7 0 0 0 14 0"/><path d="M12 18v4"/>',
    { width: 20, height: 20 }
  ),

  clock: svg('<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>', {
    width: 12,
    height: 12,
  }),

  tickSingle: svg('<path d="M4 12.5 9 17.5 20 6.5"/>', {
    width: 14,
    height: 14,
  }),

  tickDouble: svg('<path d="M1 12.5 6 17.5 17 6.5"/><path d="M7 12.5 12 17.5 23 6.5"/>', {
    width: 16,
    height: 14,
  }),

  alertCircle: svg(
    '<circle cx="12" cy="12" r="9"/><path d="M12 8v4"/><path d="M12 16h.01"/>',
    { width: 13, height: 13 }
  ),

  chevronDown: svg('<path d="M6 9l6 6 6-6"/>', { width: 20, height: 20 }),

  wifiOff: svg(
    '<path d="M2 2l20 20"/><path d="M8.5 16.4a5 5 0 0 1 7 0"/>' +
      '<path d="M5 12.9a10 10 0 0 1 3-2"/><path d="M19 12.9a10 10 0 0 0-5-2.6"/>' +
      '<path d="M12 20h.01"/>',
    { width: 16, height: 16 }
  ),

  userCheck: svg(
    '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/>' +
      '<circle cx="9" cy="7" r="4"/><path d="M17 11l2 2 4-4"/>',
    { width: 16, height: 16 }
  ),

  refresh: svg(
    '<path d="M21 12a9 9 0 1 1-3-6.7"/><path d="M21 4v5h-5"/>',
    { width: 18, height: 18 }
  ),
};
