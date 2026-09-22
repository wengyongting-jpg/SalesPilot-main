/**
 * Emoticon conversion and emoji-only detection.
 */
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';

import { convertTrailingEmoticon, isEmojiOnly } from '../../customer/js/emoji.js';

describe('convertTrailingEmoticon', () => {
  test('converts a bare emoticon followed by a space', () => {
    assert.equal(convertTrailingEmoticon(':) ').text, '\u{1F642} ');
  });

  test('converts after a word', () => {
    assert.equal(convertTrailingEmoticon('hello :) ').text, 'hello \u{1F642} ');
  });

  test('does nothing before the separator is typed', () => {
    assert.equal(convertTrailingEmoticon(':)'), null);
  });

  test('prefers the longer match', () => {
    assert.equal(convertTrailingEmoticon(':-D ').text, '\u{1F600} ');
  });

  test('leaves an emoticon embedded in a token alone', () => {
    // A URL such as http://x:) must not become an emoji.
    assert.equal(convertTrailingEmoticon('http://x:) '), null);
  });

  test('converts on a newline separator too', () => {
    const result = convertTrailingEmoticon(':)\n');
    assert.equal(result.text, '\u{1F642}\n');
  });

  test('reports how much text it replaced', () => {
    const result = convertTrailingEmoticon('hi :) ');
    assert.equal(result.removed, 3, ':) plus the space');
    assert.equal(result.inserted, '\u{1F642} ');
  });

  test('returns null for ordinary text', () => {
    assert.equal(convertTrailingEmoticon('just words '), null);
  });

  test('handles an empty string safely', () => {
    assert.equal(convertTrailingEmoticon(''), null);
  });
});

describe('isEmojiOnly', () => {
  test('a single emoji', () => {
    assert.equal(isEmojiOnly('\u{1F44D}'), true);
  });

  test('three emoji is the upper bound', () => {
    assert.equal(isEmojiOnly('\u{1F44D}\u{1F44D}\u{1F44D}'), true);
  });

  test('four emoji is too many to enlarge', () => {
    assert.equal(isEmojiOnly('\u{1F44D}\u{1F44D}\u{1F44D}\u{1F44D}'), false);
  });

  test('emoji mixed with text is not emoji-only', () => {
    assert.equal(isEmojiOnly('nice \u{1F44D}'), false);
  });

  test('whitespace between emoji is ignored for counting', () => {
    assert.equal(isEmojiOnly('\u{1F44D} \u{1F44D}'), true);
  });

  test('blank input is not emoji-only', () => {
    assert.equal(isEmojiOnly('   '), false);
    assert.equal(isEmojiOnly(''), false);
  });

  test('a multi-codepoint emoji counts as one grapheme', () => {
    // Family sequence: several codepoints joined by ZWJ.
    const family = '\u{1F468}\u200D\u{1F469}\u200D\u{1F467}';
    assert.equal(isEmojiOnly(family), true);
  });

  test('a flag counts as one grapheme', () => {
    assert.equal(isEmojiOnly('\u{1F1F8}\u{1F1EC}'), true);
  });

  test('punctuation alone is not emoji', () => {
    assert.equal(isEmojiOnly('!!!'), false);
  });
});
