/**
 * Emoji helpers.
 *
 * Two jobs:
 *   1. Convert text emoticons to emoji as the customer types (requirement 10.4).
 *   2. Detect short emoji-only messages so they can render enlarged and without
 *      a bubble background (requirement 1.8).
 *
 * A full categorised emoji picker is stretch item S1. The baseline relies on the
 * operating system emoji keyboard plus the conversion below.
 */

/** Text emoticon -> emoji. Longest keys are matched first. */
const EMOTICONS = {
  ':)': '🙂',
  ':-)': '🙂',
  ':(': '🙁',
  ':-(': '🙁',
  ':D': '😀',
  ':-D': '😀',
  ';)': '😉',
  ';-)': '😉',
  ':P': '😛',
  ':-P': '😛',
  ':p': '😛',
  ':o': '😮',
  ':O': '😮',
  ':/': '😕',
  ':|': '😐',
  ":'(": '😢',
  '<3': '❤️',
  'xD': '😆',
  'XD': '😆',
};

const EMOTICON_KEYS = Object.keys(EMOTICONS).sort((a, b) => b.length - a.length);

/** Max graphemes for a message to still count as "emoji-only". */
const EMOJI_ONLY_MAX = 3;

/**
 * Characters permitted in an emoji-only message: pictographs, emoji components,
 * variation selectors, zero-width joiners and whitespace.
 */
const EMOJI_ONLY_RE =
  /^(?:\p{Extended_Pictographic}|\p{Emoji_Component}|\uFE0F|\u200D|\s)+$/u;

/**
 * Replace a trailing emoticon once the customer types a separator after it.
 *
 * Called with the text up to the caret. Returns the replacement text, or null
 * when nothing matched, so the caller can leave the input untouched.
 *
 * @param {string} textBeforeCaret
 * @returns {{ text: string, removed: number, inserted: string } | null}
 */
export function convertTrailingEmoticon(textBeforeCaret) {
  // The separator the customer just typed (space or newline) sits at the end.
  const match = /(\s)$/.exec(textBeforeCaret);
  if (!match) return null;

  const separator = match[1];
  const beforeSeparator = textBeforeCaret.slice(0, -separator.length);

  for (const key of EMOTICON_KEYS) {
    if (!beforeSeparator.endsWith(key)) continue;

    // Require a word boundary before the emoticon so ":)" inside a URL or a
    // longer token is left alone.
    const precedingChar = beforeSeparator[beforeSeparator.length - key.length - 1];
    if (precedingChar !== undefined && !/\s/.test(precedingChar)) continue;

    return {
      text:
        beforeSeparator.slice(0, -key.length) + EMOTICONS[key] + separator,
      removed: key.length + separator.length,
      inserted: EMOTICONS[key] + separator,
    };
  }

  return null;
}

/**
 * Count graphemes, so a multi-codepoint emoji such as a flag or a ZWJ sequence
 * counts as one character.
 *
 * @param {string} text
 * @returns {number}
 */
function countGraphemes(text) {
  if (typeof Intl !== 'undefined' && typeof Intl.Segmenter === 'function') {
    const segmenter = new Intl.Segmenter(undefined, { granularity: 'grapheme' });
    let count = 0;
    for (const _ of segmenter.segment(text)) count += 1;
    return count;
  }
  // Fallback: code points. Overcounts ZWJ sequences, which only means a long
  // emoji string renders normally instead of enlarged. Acceptable degradation.
  return [...text].length;
}

/**
 * True when the message is nothing but a small number of emoji.
 *
 * @param {string} text
 * @returns {boolean}
 */
export function isEmojiOnly(text) {
  const trimmed = text.trim();
  if (!trimmed) return false;
  if (!EMOJI_ONLY_RE.test(trimmed)) return false;
  return countGraphemes(trimmed.replace(/\s/g, '')) <= EMOJI_ONLY_MAX;
}
