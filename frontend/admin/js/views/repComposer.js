/**
 * Human reply composer.
 *
 * Enabled only when the transport can deliver a human reply AND the conversation
 * is under human takeover (requirements 2.5–2.7). When it cannot, the reason is
 * stated rather than implied, and submitting is impossible rather than failing.
 *
 * The draft survives a failed send (requirement 2.9): losing a representative's
 * typed reply is worse than showing an error.
 */
import { strings } from '../strings.js';
import { el, clear } from '../dom.js';

/**
 * @param {object} deps
 * @param {HTMLElement} deps.el
 * @param {(text: string) => void} deps.onSend
 * @param {(text: string) => void} deps.onDraftChange
 */
export function createRepComposer({ el: root, onSend, onDraftChange }) {
  let lastSignature = null;
  let inputRef = null;

  const reason = (text) =>
    el('div', { className: 'composer__reason', attrs: { role: 'note' } }, [
      el('span', { text }),
    ]);

  /**
   * @returns {{ enabled: boolean, note: string|null }}
   */
  function gate(state) {
    if (!state.selectedId || !state.conversation.opportunity) {
      return { enabled: false, note: strings.composer.noConversation };
    }
    if (!state.capabilities.repReply) {
      return { enabled: false, note: strings.composer.unsupported };
    }
    if (!state.conversation.opportunity.humanTakeover) {
      return { enabled: false, note: strings.composer.needsTakeover };
    }
    return { enabled: true, note: null };
  }

  return {
    render(state) {
      const { enabled, note } = gate(state);
      const { inFlight, error, draft } = state.compose;
      const signature = `${enabled}|${note}|${inFlight}|${Boolean(error)}|${state.selectedId}`;
      if (signature === lastSignature) {
        // Keep the textarea in step without rebuilding and losing the caret.
        if (inputRef && inputRef.value !== draft && document.activeElement !== inputRef) {
          inputRef.value = draft;
        }
        return;
      }
      lastSignature = signature;

      clear(root);

      if (!enabled) {
        root.append(reason(note));
        inputRef = null;
        return;
      }

      const input = el('textarea', {
        className: 'composer__input',
        attrs: {
          rows: 2,
          placeholder: strings.composer.placeholder,
          'aria-label': strings.composer.inputLabel,
        },
        on: {
          input: (event) => onDraftChange(event.target.value),
          keydown: (event) => {
            if (event.key !== 'Enter' || event.shiftKey) return;
            event.preventDefault();
            submit();
          },
        },
      });
      input.value = draft;
      inputRef = input;

      const button = el('button', {
        className: 'btn btn--primary',
        text: inFlight ? strings.composer.sending : strings.composer.send,
        attrs: { type: 'submit', disabled: inFlight },
      });

      function submit() {
        const text = input.value.trim();
        if (!text || inFlight) return;
        onSend(text);
      }

      const form = el(
        'form',
        {
          className: 'composer__form',
          on: {
            submit: (event) => {
              event.preventDefault();
              submit();
            },
          },
        },
        [input, button]
      );

      root.append(form);
      // The operator's identity is already in the sidebar; repeating it here was
      // redundant noise directly under the input.
      if (error) {
        root.append(
          el('div', { className: 'composer__error', text: strings.composer.failed })
        );
      }
    },
  };
}
