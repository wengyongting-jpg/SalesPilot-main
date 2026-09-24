# UX specification — Customer chat UI

Concrete values for `frontend/customer/css/tokens.css` and `app.css`. Every value
here is a token; component CSS references `var(--*)` and never a literal.

The look follows generic messaging conventions. It is **not** a WhatsApp clone: no
WhatsApp logo, wordmark, WhatsApp Sans font, or WhatsApp notification sound. Where
a value was informed by public open-source recreations of messenger layouts, note
it in a CSS comment.

---

## 1. Layout

### Desktop, viewport ≥ 900px

A phone-shaped frame centred on a neutral backdrop.

```
┌──────────────── page backdrop ────────────────┐
│                                               │
│         ┌───── phone frame ─────┐              │
│         │ header          64px  │              │
│         │ banner (optional)     │              │
│         │                       │              │
│         │   message list        │  flex: 1     │
│         │            [jump btn] │              │
│         │ quick replies (opt)   │              │
│         │ composer        auto  │              │
│         └───────────────────────┘              │
└───────────────────────────────────────────────┘
```

| Token | Value |
| --- | --- |
| `--frame-width` | `400px` |
| `--frame-height` | `min(844px, 92vh)` |
| `--frame-radius` | `28px` |
| `--frame-shadow` | `0 12px 40px rgb(0 0 0 / 0.18)` |
| `--header-height` | `64px` |

### Tablet, 600–899px

Frame drops to `--frame-width: 100%`, `max-width: 520px`, radius `16px`, height
`100vh`, shadow removed.

### Mobile, < 600px

Full viewport, no frame, no radius, no shadow. Use `100dvh` so the mobile browser
chrome does not clip the composer (Requirement 14.3). The composer is the last
flex child and the message list scrolls, which keeps the composer pinned without
`position: fixed`.

### Breakpoints

| Token | Value |
| --- | --- |
| `--bp-mobile` | `600px` |
| `--bp-desktop` | `900px` |

---

## 2. Colour — light theme

Default and only theme in the first delivery. Dark theme is stretch S4.

### Surfaces

| Token | Value | Use |
| --- | --- | --- |
| `--c-backdrop` | `#d3d9de` | Page behind the frame |
| `--c-header` | `#008069` | Header bar |
| `--c-header-text` | `#ffffff` | Header text and icons |
| `--c-chat-bg` | `#efeae2` | Message list background |
| `--c-composer-bg` | `#f0f2f5` | Composer bar |
| `--c-input-bg` | `#ffffff` | Text input field |

### Bubbles

| Token | Value | Use |
| --- | --- | --- |
| `--c-bubble-out` | `#d9fdd3` | Outgoing bubble |
| `--c-bubble-in` | `#ffffff` | Incoming bubble |
| `--c-bubble-text` | `#111b21` | Body text, both directions |
| `--c-bubble-meta` | `#667781` | Timestamps, tick glyphs |
| `--c-bubble-shadow` | `0 1px 0.5px rgb(11 20 26 / 0.13)` | Both bubbles |

### Accent and status

| Token | Value | Use |
| --- | --- | --- |
| `--c-accent` | `#008069` | Send button, focus ring, links-as-text emphasis |
| `--c-tick-read` | `#53bdeb` | Double tick, read state only |
| `--c-danger` | `#d32f2f` | Failed message, retry affordance |
| `--c-warning-bg` | `#fff3cd` | Offline banner background |
| `--c-warning-text` | `#664d03` | Offline banner text |
| `--c-handoff-bg` | `#e7f3ff` | Handoff banner background |
| `--c-handoff-text` | `#0b5394` | Handoff banner text |
| `--c-system-bg` | `#e2f0d9` | System message chip |
| `--c-system-text` | `#3d5a3d` | System message text |
| `--c-separator-bg` | `#e1f2fa` | Date separator chip |
| `--c-separator-text` | `#54656f` | Date separator text |

Contrast note: `--c-bubble-meta` on `--c-bubble-in` and `--c-bubble-out` is used
only for 12px metadata and clears WCAG AA for that size class. Never use it for
body copy.

---

## 3. Typography

No web font download and no proprietary font. System stack only:

```css
--font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
             "Helvetica Neue", Arial, sans-serif;
--font-emoji: "Apple Color Emoji", "Segoe UI Emoji", "Noto Color Emoji", sans-serif;
```

| Token | Size / line-height / weight | Use |
| --- | --- | --- |
| `--t-header-name` | `17px / 22px / 600` | Contact name |
| `--t-header-status` | `13px / 17px / 400` | AI label, presence, typing |
| `--t-body` | `15px / 20px / 400` | Message body |
| `--t-meta` | `12px / 16px / 400` | Timestamp, ticks |
| `--t-separator` | `12.5px / 17px / 500` | Date separator, system message |
| `--t-card-title` | `15px / 20px / 600` | Product card title |
| `--t-card-fact` | `14px / 19px / 400` | Product card fact |
| `--t-disclaimer` | `11px / 15px / 400` | Demo disclaimer |
| `--t-chip` | `14px / 18px / 500` | Quick-reply chip |

Emoji-only messages up to three characters render at `32px` with no bubble
background (Requirement 1.8).

The demo disclaimer is small but must stay legible and never be clipped: allow it
to wrap freely, no `max-height`, no ellipsis, no collapse control.

---

## 4. Spacing and shape

```css
--sp-1: 2px;   --sp-2: 4px;   --sp-3: 6px;   --sp-4: 8px;
--sp-5: 12px;  --sp-6: 16px;  --sp-7: 24px;  --sp-8: 32px;
```

| Token | Value |
| --- | --- |
| `--bubble-radius` | `7.5px` |
| `--bubble-max-width` | `75%` |
| `--bubble-pad-y` | `6px` |
| `--bubble-pad-x` | `9px` |
| `--bubble-gap-grouped` | `2px` |
| `--bubble-gap-new-sender` | `12px` |
| `--list-pad-x` | `16px` |
| `--list-pad-y` | `12px` |
| `--chip-radius` | `16px` |
| `--card-radius` | `8px` |

### Bubble tail

Rendered with a CSS pseudo-element on the first bubble of a run only
(Requirement 1.2). Approximately 8px wide and 13px tall, colour-matched to the
bubble, positioned at the top outer corner: `left: -8px` for incoming,
`right: -8px` for outgoing. Grouped followers get `--bubble-radius` on all corners
and no tail.

### Timestamp placement

Inline at the bubble's bottom-right, on the same line as the text when it fits.
Reserve trailing space so the timestamp never overlaps the last word: pad the text
container right by 54px for outgoing (timestamp plus tick) and 38px for incoming.

---

## 5. Components

### Header

Height `--header-height`, background `--c-header`. Left to right: circular avatar
36px with `--business.avatarInitials`; a stacked block with the business name in
`--t-header-name` and a status line in `--t-header-status`; then controls.

The status line is the AI disclosure point (Requirement 3.6) and changes with
state:

| State | Status line |
| --- | --- |
| Idle, AI active | `AI Assistant · online` |
| Send in flight | `typing…` |
| Human takeover | `<Rep name> · CareSure representative` |

The AI label must never disappear while the AI is answering. Only a genuine human
takeover replaces it.

### Message list

Vertical scroll container, background `--c-chat-bg`. Padding `--list-pad-y`
`--list-pad-x`. Marked as a polite live region so appended messages are announced
(Requirement 14.5).

### Date separator

Centred chip, `--c-separator-bg`, `--c-separator-text`, `--t-separator`, padding
`--sp-2` `--sp-5`, radius `--chip-radius`, margin `--sp-6` auto.
Labels: `Today`, `Yesterday`, else `D MMMM YYYY`.

### System message

Same geometry as the date separator but `--c-system-bg` / `--c-system-text`, and
the text is left-aligned inside a centred chip that may wrap to several lines.
Used for takeover notices (Requirement 6.5, 7.1).

### Ticks

12px glyphs, inline SVG, placed after the timestamp on outgoing messages only.

| Status | Glyph | Colour |
| --- | --- | --- |
| `sending` | clock outline | `--c-bubble-meta` |
| `sent` | single tick | `--c-bubble-meta` |
| `read` | double tick | `--c-tick-read` |
| `failed` | filled circle with exclamation | `--c-danger` |

`failed` additionally renders a text retry control beneath the bubble in
`--c-danger`, `--t-meta`, with an accessible name of "Retry sending message". When
backend idempotency is unavailable, extend its accessible description to warn that
retrying may duplicate the message (Requirement 2.10).

### Typing indicator

An incoming-position bubble containing three 7px dots in `--c-bubble-meta`,
spaced `--sp-2`. Each dot animates opacity `0.35 → 1 → 0.35` over
`--dur-typing`, staggered by 160ms. Removed the moment a reply lands or the send
fails — never left running.

### Product card

Inside an incoming bubble, radius `--card-radius`, a 3px left border in
`--c-accent`, padding `--sp-5`. Title in `--t-card-title`. Up to four facts as a
list in `--t-card-fact` with `--sp-3` between items. Facts are verbatim backend
text (Requirement 6.2). If any fact mentions a premium, the disclaimer renders
beneath the list in `--t-disclaimer`, `--c-bubble-meta`.

### Quick-reply chips

A horizontally scrollable row directly above the composer. Each chip: background
`--c-input-bg`, 1px border `--c-accent`, text `--c-accent`, `--t-chip`, padding
`--sp-3` `--sp-5`, radius `--chip-radius`, gap `--sp-3`. Maximum three chips
(Requirement 5.5). The row animates out on tap or on typing.

### Composer

Background `--c-composer-bg`, padding `--sp-4` `--sp-5`. A rounded input
(`--c-input-bg`, radius `--chip-radius`, padding `--sp-4` `--sp-5`) that
auto-grows from one line to five, then scrolls internally (Requirement 10.3).

A single 44px circular action button on the right, background `--c-accent`:

| Composer state | Glyph | Enabled |
| --- | --- | --- |
| Empty or whitespace-only | microphone | no |
| Has content | paper-plane | yes |

The microphone is presentational only — voice notes are out of scope. It carries
`aria-hidden` on the glyph and the button stays disabled in that state, so no
keyboard user can reach a dead control.

### Banners

Full-width strip under the header, `--t-header-status`, padding `--sp-4`
`--sp-5`. Offline uses `--c-warning-bg` / `--c-warning-text`; handoff uses
`--c-handoff-bg` / `--c-handoff-text`. Both can be visible at once; offline sits
above handoff.

### Jump to latest

Floating circular button 40px, bottom-right of the list, offset `--sp-6`,
background `--c-input-bg`, chevron in `--c-bubble-meta`, shadow
`--c-bubble-shadow`. When unread is greater than zero, a badge in `--c-accent`
with white `--t-meta` text sits at its top-right (Requirement 4.3).

---

## 6. Motion

```css
--dur-instant: 90ms;
--dur-fast:    140ms;
--dur-base:    200ms;
--dur-slow:    320ms;
--dur-typing:  1200ms;
--ease-out:    cubic-bezier(0.22, 0.61, 0.36, 1);
--ease-in-out: cubic-bezier(0.45, 0.05, 0.55, 0.95);
```

| Animation | Duration / easing | Detail |
| --- | --- | --- |
| Message pop-in | `--dur-base` `--ease-out` | `opacity 0→1`, `translateY 8px→0`, `scale 0.96→1` |
| Send button glyph swap | `--dur-fast` | Cross-fade plus `scale 0.8→1` |
| Tick change | `--dur-instant` | Opacity cross-fade, no movement |
| Typing dots | `--dur-typing` infinite | Staggered 160ms |
| Quick replies in | `--dur-base` `--ease-out` | Slide up 8px plus fade |
| Quick replies out | `--dur-fast` | Fade only |
| Banner in/out | `--dur-base` `--ease-in-out` | Height plus fade |
| Jump-to-latest | `--dur-fast` | Fade plus `scale 0.9→1` |
| Smooth scroll | `--dur-slow` | `scroll-behavior: smooth` |

Under `@media (prefers-reduced-motion: reduce)`, set every duration above to `1ms`
except the typing indicator, which switches to a static three-dot glyph rather
than animating. Scroll becomes `auto`.

---

## 7. States

### Empty

Centred in the message list: 56px circular avatar with business initials, the
business name in `--t-card-title`, the configured welcome message in `--t-body`
with `--c-bubble-meta`, max-width 280px. No decorative illustration.

### Loading history

Three skeleton bubbles — incoming, outgoing, incoming — at 60%, 45% and 70% width,
background `--c-bubble-in` at 60% opacity, pulsing opacity `0.6 → 0.9` over
`--dur-slow` alternating. Never show a spinner over an empty list.

### History error

Centred block: short message from `strings.js`, plus a "Try again" text button in
`--c-accent`. Any messages already rendered stay on screen (Requirement 12.3).

### Send failure

Handled at the bubble level, not globally. The failed bubble keeps its text at
full opacity — the customer's words are never dimmed or hidden — and gains the
danger tick plus retry control.

### Offline

Banner only. The composer stays enabled so the customer can finish their thought;
the send attempt will fail and surface per-message retry. Blocking input would
lose typed text, which is worse than a failed send.

---

## 8. Sound and notifications (stretch)

Not in the first delivery. When built:

- Any sound must be self-produced or openly licensed with attribution recorded in
  `frontend/customer/README` — never WhatsApp's tone. Default to muted, with the
  mute preference persisted in `localStorage`.
- Browser notifications must be requested on an explicit user gesture, never on
  page load, and only fire while `document.hidden` is true.

---

## 9. Asset inventory

All icons are hand-authored inline SVG, 24px viewBox, `currentColor`, no external
files and no icon font:

`send` (paper plane), `mic`, `clock`, `tick-single`, `tick-double`,
`alert-circle`, `chevron-down`, `wifi-off`, `user-check` (handoff).

No raster images. The avatar is initials on a coloured circle. This keeps the app
fully offline-capable and free of third-party brand assets.
