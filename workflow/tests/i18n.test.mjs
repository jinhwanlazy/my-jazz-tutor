import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';

const saved = new Map();
globalThis.localStorage = {getItem: key => saved.get(key), setItem: (key, value) => saved.set(key, value)};
const catalog = JSON.parse(await readFile(new URL('../translations.json', import.meta.url), 'utf8'));
globalThis.fetch = async () => ({ok: true, json: async () => catalog});
const {tr, locale, setLocale, loadTranslations} = await import('../i18n.mjs');
await loadTranslations();

test('language selection persists while interpolation preserves literal values', () => {
  assert.equal(locale(), 'en');
  assert.equal(setLocale('ko'), true);
  assert.equal(saved.get('my-jazz-tutor.language'), 'ko');
  assert.equal(tr`Bar ${3} · beat ${2}`, '3마디 · 2박');
  assert.equal(tr`Key ${'$&{0}'}`, '$&{0} 키');
  assert.equal(tr('Assessment pending'), '판정 보류');
  assert.match(tr('bpm: a number between 40 and 120 is required.'), /40~120/);
  assert.match(tr('bpm: a number between 40 and 120 is required.'), /[가-힣]/);
  setLocale('en');
  assert.equal(tr`Bar ${3} · beat ${2}`, 'Bar 3 · beat 2');
});

test('blocked browser storage does not prevent language switching', () => {
  globalThis.localStorage.setItem = () => { throw new Error('blocked'); };
  assert.equal(setLocale('ko'), false);
  assert.equal(locale(), 'ko');
  assert.equal(tr('Settings'), '설정');
  assert.throws(() => setLocale('unknown'));
  assert.equal(locale(), 'ko');
});
