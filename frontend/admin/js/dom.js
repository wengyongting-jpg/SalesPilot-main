/**
 * Minimal DOM construction helpers.
 *
 * `text` always goes through `textContent`. `html` exists only for hand-authored
 * icon constants and must never receive backend data — message text, case
 * summaries, knowledge facts and model prompts are all untrusted.
 */

/**
 * @param {string} tag
 * @param {object} [options]
 * @param {Array<Node|null|undefined|false>|Node} [children]
 * @returns {HTMLElement}
 */
export function el(tag, options = {}, children = []) {
  const node = document.createElement(tag);

  if (options.className) node.className = options.className;
  if (options.text !== undefined && options.text !== null) {
    node.textContent = String(options.text);
  }
  if (options.html !== undefined) node.innerHTML = options.html;

  if (options.attrs) {
    for (const [key, value] of Object.entries(options.attrs)) {
      if (value === null || value === undefined || value === false) continue;
      node.setAttribute(key, value === true ? '' : String(value));
    }
  }
  if (options.on) {
    for (const [event, handler] of Object.entries(options.on)) {
      node.addEventListener(event, handler);
    }
  }
  if (options.style) Object.assign(node.style, options.style);

  const list = Array.isArray(children) ? children : [children];
  for (const child of list) {
    if (child) node.append(child);
  }
  return node;
}

export const clear = (node) => node.replaceChildren();

/** A labelled key/value row. */
export const kvRow = (key, value, muted = false) => [
  el('div', { className: 'kv__key', text: key }),
  el('div', {
    className: muted ? 'kv__val kv__val--muted' : 'kv__val',
    text: value,
  }),
];

/** A badge with text; colour is always paired with a label. */
export const badge = (text, modifier = 'badge--neutral', title) =>
  el('span', {
    className: `badge ${modifier}`,
    text,
    attrs: title ? { title } : {},
  });

/** Section wrapper used across panels. */
export const section = (title, children) =>
  el('div', { className: 'panel-section' }, [
    el('div', { className: 'panel-section__title', text: title }),
    ...(Array.isArray(children) ? children : [children]),
  ]);

/** Centred state block: empty, loading or error. */
export function stateBlock({ title, body, actionLabel, onAction, variant }) {
  return el(
    'div',
    { className: variant ? `state state--${variant}` : 'state' },
    [
      title ? el('div', { className: 'state__title', text: title }) : null,
      body ? el('div', { className: 'state__body', text: body }) : null,
      actionLabel
        ? el('button', {
            className: 'btn btn--secondary',
            text: actionLabel,
            attrs: { type: 'button' },
            on: { click: onAction },
          })
        : null,
    ]
  );
}

/** Simple skeleton placeholder. */
export const skeleton = (rows = 4) =>
  el(
    'div',
    { className: 'panel-section' },
    Array.from({ length: rows }, () => el('div', { className: 'skeleton-row' }))
  );
