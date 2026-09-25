/** Backend-authored scoring provenance; this view never calculates points. */
import { el, clear } from '../dom.js';

export function createScoreEvidence({ el: root }) {
  let previous = '';
  return {
    render(state) {
      const evidence = state.conversation.opportunity?.scoreHistory?.at(-1)?.evidence;
      const key = JSON.stringify(evidence ?? null);
      if (key === previous) return;
      previous = key;
      clear(root);
      root.append(el('h2', { text: 'Score evidence' }));
      if (!evidence || !Object.keys(evidence).length) {
        root.append(el('p', { text: 'No per-rule evidence is recorded for this score.' }));
        return;
      }
      root.append(el('p', {
        text: `Rule ${evidence.rule_version} · latest message ${evidence.latest_message_id ?? 'unknown'}`,
      }));
      for (const [name, dimension] of Object.entries(evidence.dimensions ?? {})) {
        root.append(el('div', { className: 'debug-dimension' }, [
          el('strong', { text: `${name.replaceAll('_', ' ')}: ${dimension.points}` }),
          el('p', { text: dimension.rule }),
          el('small', { text: `Source messages: ${dimension.message_ids?.join(', ') || 'not linked in earlier history'}` }),
        ]));
      }
      root.append(el('h3', { text: 'Calculations' }));
      for (const formula of Object.values(evidence.calculation ?? {})) {
        root.append(el('p', { text: formula }));
      }
    },
  };
}
