/**
 * Lightweight Markdown parser for message text.
 *
 * Handles common patterns from LLM output:
 * - **bold** → <strong>
 * - List items starting with `-` or `*`
 * - Special sections like **Observation:** and **Response:**
 *
 * Security: All user content goes through textContent, never innerHTML.
 * Only the structure is converted to DOM elements.
 */

/**
 * Parse markdown-like text into DOM elements.
 * @param {string} text - The message text
 * @returns {DocumentFragment} - Safe DOM structure
 */
export function parseMessageMarkdown(text) {
  const fragment = document.createDocumentFragment();
  const lines = text.split('\n');

  let i = 0;
  while (i < lines.length) {
    const line = lines[i].trim();

    // Skip empty lines
    if (!line) {
      i++;
      continue;
    }

    // Handle special sections (Observation, Response)
    if (line.match(/^\*\*(?:Observation|Response|Note):\*\*/i)) {
      const section = parseSpecialSection(line);
      fragment.appendChild(section);
      i++;
      continue;
    }

    // Handle list items
    if (line.match(/^[-*]\s/)) {
      const list = parseListBlock(lines, i);
      fragment.appendChild(list.element);
      i = list.nextIndex;
      continue;
    }

    // Regular paragraph with inline formatting
    const para = document.createElement('p');
    para.className = 'message-paragraph';
    parseInlineFormatting(line, para);
    fragment.appendChild(para);
    i++;
  }

  return fragment;
}

/**
 * Parse special sections like **Observation:** or **Response:**
 */
function parseSpecialSection(line) {
  const div = document.createElement('div');
  div.className = 'message-section';

  // Extract section name
  const match = line.match(/^\*\*(.*?):\*\*/);
  if (match) {
    const label = document.createElement('span');
    label.className = 'message-section-label';
    label.textContent = match[1] + ':';
    div.appendChild(label);

    // Remaining text after the label
    const rest = line.substring(match[0].length).trim();
    if (rest) {
      const text = document.createElement('span');
      text.className = 'message-section-text';
      parseInlineFormatting(rest, text);
      div.appendChild(text);
    }
  } else {
    div.textContent = line;
  }

  return div;
}

/**
 * Parse a block of list items
 */
function parseListBlock(lines, startIndex) {
  const ul = document.createElement('ul');
  ul.className = 'message-list';

  let i = startIndex;
  while (i < lines.length) {
    const line = lines[i].trim();

    // Stop at non-list line
    if (!line.match(/^[-*]\s/)) {
      break;
    }

    const li = document.createElement('li');
    const content = line.replace(/^[-*]\s+/, '');
    parseInlineFormatting(content, li);
    ul.appendChild(li);
    i++;
  }

  return { element: ul, nextIndex: i };
}

/**
 * Parse inline formatting like **bold**
 * Security: Uses textContent for all user input
 */
function parseInlineFormatting(text, container) {
  // Split by **bold** markers
  const parts = text.split(/(\*\*.*?\*\*)/g);

  parts.forEach(part => {
    if (!part) return;

    // Check if it's a bold section
    const boldMatch = part.match(/^\*\*(.*?)\*\*$/);
    if (boldMatch) {
      const strong = document.createElement('strong');
      strong.textContent = boldMatch[1];
      container.appendChild(strong);
    } else {
      // Regular text
      const textNode = document.createTextNode(part);
      container.appendChild(textNode);
    }
  });
}

/**
 * Check if text contains markdown-like formatting
 */
export function hasMarkdownFormatting(text) {
  return text.includes('**') ||
         text.match(/^[-*]\s/m) ||
         text.match(/^\*\*(?:Observation|Response):/i);
}
