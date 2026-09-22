/**
 * Customer identity presentation.
 *
 * `opportunity_id` is the key; `customer_name` is a label. The backend keys
 * opportunities on id alone, so two customers may share a name, and the name is
 * written once at creation and never updated afterwards.
 *
 * Therefore: initials come from the name, but the avatar colour is derived from
 * the **id**, so two customers called Sarah are visually distinct. The id is also
 * shown on every row (requirement 1.3, 1.4).
 */

/** Hues chosen to stay legible against white text. */
const HUES = [210, 262, 288, 340, 8, 24, 160, 186];

/** Deterministic, stable, and cheap. Not a security hash. */
function hashCode(value) {
  let hash = 0;
  for (let i = 0; i < value.length; i += 1) {
    hash = (hash << 5) - hash + value.charCodeAt(i);
    hash |= 0;
  }
  return Math.abs(hash);
}

/**
 * @param {string} name
 * @returns {string} one or two uppercase initials
 */
export function initials(name) {
  const parts = String(name || '')
    .trim()
    .split(/\s+/)
    .filter(Boolean);
  if (parts.length === 0) return '?';
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

/**
 * @param {string} id opportunity id
 * @returns {string} a CSS colour
 */
export function avatarColour(id) {
  const hue = HUES[hashCode(String(id || '')) % HUES.length];
  return `hsl(${hue} 42% 42%)`;
}

/**
 * Apply both to an avatar element.
 *
 * @param {HTMLElement} el
 * @param {{ id: string, name: string }} customer
 */
export function applyAvatar(el, { id, name }) {
  el.textContent = initials(name);
  el.style.background = avatarColour(id);
  el.setAttribute('aria-hidden', 'true');
}
