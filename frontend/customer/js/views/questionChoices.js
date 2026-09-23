/** A channel-neutral question shown as a tappable list in the browser demo. */
export function createQuestionChoices({ el, onSelect, onOther }) {
  let previous = '';
  return {
    render(state) {
      const question = state.assistant.humanTakeover ? null : state.question;
      const key = question ? `${question.field}:${question.options.map((o) => o.id).join(',')}` : '';
      if (key === previous) return;
      previous = key;
      el.replaceChildren();
      if (!question) return;
      el.setAttribute('aria-label', question.prompt);
      for (const option of question.options) {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'question-choice';
        button.textContent = option.label;
        button.addEventListener('click', () => {
          if (option.label === 'Something else') onOther();
          else onSelect(option.id);
        });
        el.append(button);
      }
    },
  };
}
