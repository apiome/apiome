import assert from 'node:assert/strict';
import {describe, it} from 'node:test';

import {MOD_LABEL, splitChord} from '../src/components/Kbd/chord.ts';

describe('splitChord', () => {
  it('splits a chord on +', () => {
    assert.deepEqual(splitChord('Shift+?'), ['Shift', '?']);
  });
  it('expands Mod to the platform-neutral label', () => {
    assert.deepEqual(splitChord('Mod+K'), [MOD_LABEL, 'K']);
  });
  it('writes the plus key as Plus', () => {
    assert.deepEqual(splitChord('Mod+Plus'), [MOD_LABEL, '+']);
  });
  it('trims whitespace and drops empty keys', () => {
    assert.deepEqual(splitChord(' Ctrl + + K '), ['Ctrl', 'K']);
    assert.deepEqual(splitChord(''), []);
  });
  it('keeps a single key as one label', () => {
    assert.deepEqual(splitChord('Esc'), ['Esc']);
  });
});
