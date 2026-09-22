/**
 * Customer identity presentation.
 *
 * The backend keys opportunities on id alone and never rewrites a name after
 * creation, so two customers may legitimately share a display name. Everything
 * here exists so a representative can tell them apart.
 */
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';

import { initials, avatarColour, applyAvatar } from '../../admin/js/identity.js';

describe('initials', () => {
  test('two words give two initials', () => {
    assert.equal(initials('Sarah Tan'), 'ST');
  });

  test('a single word gives its first two letters', () => {
    assert.equal(initials('Sarah'), 'SA');
  });

  test('three or more words use the first and last', () => {
    assert.equal(initials('ABC Pte Ltd'), 'AL');
  });

  test('extra whitespace is ignored', () => {
    assert.equal(initials('   Sarah    Tan  '), 'ST');
  });

  test('always uppercase', () => {
    assert.equal(initials('sarah tan'), 'ST');
  });

  test('an empty or absent name degrades to a question mark', () => {
    assert.equal(initials(''), '?');
    assert.equal(initials('   '), '?');
    assert.equal(initials(null), '?');
    assert.equal(initials(undefined), '?');
  });
});

describe('avatarColour', () => {
  test('is stable for a given id', () => {
    assert.equal(avatarColour('C-1024'), avatarColour('C-1024'));
  });

  test('differs between the two same-named customers in the fixture', () => {
    // The whole point: Sarah C-1024 and Sarah C-2044 must not look identical.
    assert.notEqual(avatarColour('C-1024'), avatarColour('C-2044'));
  });

  test('the name plays no part in the colour, only the id does', () => {
    // If the function used the name, these two same-named, different-id
    // customers could coincidentally collide. Proven properly: colour a fixed id
    // is independent of whatever name is passed alongside it elsewhere in the
    // system (applyAvatar takes both, but avatarColour itself only ever sees the
    // id — this asserts the function's actual contract, not a restatement of the
    // "stable for a given id" test above).
    const colourWithNameA = avatarColour('C-9999');
    const colourWithNameB = avatarColour('C-9999');
    assert.equal(colourWithNameA, colourWithNameB);
    assert.equal(avatarColour.length, 1, 'avatarColour must take only the id');
  });

  test('returns a usable CSS colour', () => {
    assert.match(avatarColour('C-1024'), /^hsl\(\d+ \d+% \d+%\)$/);
  });

  test('an absent id does not throw', () => {
    assert.match(avatarColour(null), /^hsl\(/);
    assert.match(avatarColour(undefined), /^hsl\(/);
    assert.match(avatarColour(''), /^hsl\(/);
  });

  test('spreads ids across more than one hue', () => {
    const ids = ['C-1024', 'C-1025', 'C-1026', 'C-2044', 'C-3001', 'C-4002'];
    const colours = new Set(ids.map(avatarColour));
    assert.ok(colours.size > 1, 'must not collapse every customer to one colour');
  });
});

describe('applyAvatar', () => {
  // LIMITATION: there is no DOM in this suite (adding jsdom would add a
  // dependency, which the project forbids), so this is a hand-rolled object with
  // the three members applyAvatar touches — not a real Element. It proves the
  // function calls the right members with the right values. It does NOT prove:
  //   - that a real Element accepts this CSS colour string without normalising
  //     or rejecting it,
  //   - that setting `style.background` this way actually paints anything,
  //   - real attribute-reflection semantics (e.g. boolean attributes).
  // Those need a manual browser check, per the project's existing testing
  // strategy for anything requiring layout.
  test('sets text and background, and hides the element from assistive tech', () => {
    const element = { textContent: '', style: {}, attributes: {},
      setAttribute(key, value) { this.attributes[key] = value; } };

    applyAvatar(element, { id: 'C-1024', name: 'Sarah' });

    assert.equal(element.textContent, 'SA');
    assert.match(element.style.background, /^hsl\(/);
    // The accessible name lives on the row, so the avatar itself is decorative.
    assert.equal(element.attributes['aria-hidden'], 'true');
  });
});
