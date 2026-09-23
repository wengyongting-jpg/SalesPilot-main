/** The representative's first-glance assessment and on-demand handoff brief. */
import { el, clear, badge } from '../dom.js';
import { priorityClass } from '../format.js';

export function createOverview({ el: root, onGenerateBrief, onOpenDebug }) {
  return {
    render(state) {
      const opportunity = state.conversation.opportunity;
      clear(root);
      if (!opportunity) {
        root.append(el('p', { text: 'Select a conversation to see its essentials.' }));
        return;
      }
      const reason = state.conversation.linkedCase?.reason
        ?? opportunity.pendingHandoffReason
        ?? opportunity.mainConcern
        ?? 'Not yet established';
      root.append(
        el('h2', { text: 'At a glance' }),
        el('div', { className: 'overview__priority' }, [
          badge(opportunity.priority ?? '—', priorityClass(opportunity.priority)),
          el('strong', { text: `Score ${opportunity.finalScore ?? '—'}` }),
        ]),
        el('h3', { text: 'Why staff attention?' }),
        el('p', { text: reason }),
        el('h3', { text: 'Keywords' }),
        el('p', { text: opportunity.signals?.slice(0, 5).join(' · ') || 'None yet' }),
      );
      if (state.conversation.linkedCase) {
        root.append(el('button', {
          className: 'btn btn--primary btn--small',
          text: state.brief.loading ? 'Generating…' : 'Generate handoff brief',
          attrs: { type: 'button', disabled: state.brief.loading },
          on: { click: () => onGenerateBrief(opportunity.id) },
        }));
      }
      if (state.brief.text) {
        root.append(
          el('p', { className: 'overview__source', text: `Draft · ${state.brief.source}` }),
          el('pre', { className: 'overview__brief', text: state.brief.text }),
        );
      } else if (state.brief.error) {
        root.append(el('p', { text: state.brief.error }));
      }
      root.append(el('button', {
        className: 'btn btn--link', text: 'Detailed assessment and diagnostics',
        attrs: { type: 'button' }, on: { click: onOpenDebug },
      }));
    },
  };
}
