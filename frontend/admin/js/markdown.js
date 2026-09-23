/** Safe, dependency-free subset of the customer message formatter. */
export function formatAiMessage(value) {
  const fragment = document.createDocumentFragment();
  let list = null;
  for (const source of String(value ?? '').split('\n')) {
    const line = source.trim();
    if (!line) {
      list = null;
      continue;
    }
    const item = /^[-*]\s+(.+)$/.exec(line);
    if (item) {
      if (!list) {
        list = document.createElement('ul');
        fragment.append(list);
      }
      const li = document.createElement('li');
      appendInline(li, item[1]);
      list.append(li);
      continue;
    }
    list = null;
    const paragraph = document.createElement('p');
    appendInline(paragraph, line);
    fragment.append(paragraph);
  }
  return fragment;
}

function appendInline(parent, value) {
  for (const part of value.split(/(\*\*[^*\n]+\*\*)/g)) {
    if (!part) continue;
    if (part.startsWith('**') && part.endsWith('**')) {
      const strong = document.createElement('strong');
      strong.textContent = part.slice(2, -2);
      parent.append(strong);
    } else {
      parent.append(document.createTextNode(part));
    }
  }
}
