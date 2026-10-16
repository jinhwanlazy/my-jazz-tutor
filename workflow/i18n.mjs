const storageKey = 'my-jazz-tutor.language';
let language = 'en', catalog = {}, patterns = [];
try {
  const saved = globalThis.localStorage?.getItem(storageKey);
  if (saved === 'en' || saved === 'ko') language = saved;
} catch { /* Language switching still works when browser storage is unavailable. */ }

export function locale() { return language; }

export function setLocale(value) {
  if (!['en', 'ko'].includes(value)) throw new Error('Unsupported display language.');
  language = value;
  try {
    globalThis.localStorage.setItem(storageKey, value);
    return true;
  } catch { return false; }
}

const placeholder = /\{([a-zA-Z_][a-zA-Z_0-9]*|\d+)\}/g;
const escapeRegex = text => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const format = (text, values) => text.replace(placeholder, (token, key) => Object.hasOwn(values, key) ? String(values[key]) : token);

export async function loadTranslations() {
  const response = await fetch('/translations.json');
  if (!response.ok) throw new Error('Could not load translations.');
  const data = await response.json();
  catalog = data.ko;
  // Match already formatted server errors against known message templates only.
  patterns = Object.entries(catalog).flatMap(([english, korean]) => {
    const matches = [...english.matchAll(placeholder)];
    if (!matches.length || english === korean) return [];
    let pattern = '^', offset = 0;
    for (const match of matches) {
      pattern += escapeRegex(english.slice(offset, match.index)) + '([\\s\\S]*?)';
      offset = match.index + match[0].length;
    }
    pattern += escapeRegex(english.slice(offset)) + '$';
    return [{regex: new RegExp(pattern), keys: matches.map(match => match[1]), korean,
             specificity: english.replace(placeholder, '').length}];
  }).sort((a, b) => b.specificity - a.specificity);
}

export function tr(message, ...values) {
  if (Array.isArray(message)) {
    const key = message.reduce((text, part, i) => text + part + (i < values.length ? `{${i}}` : ''), '');
    return format(language === 'ko' ? catalog[key] ?? key : key, values);
  }
  if (language !== 'ko') return message;
  if (Object.hasOwn(catalog, message)) return catalog[message];
  for (const {regex, keys, korean} of patterns) {
    const match = regex.exec(message);
    if (match) return format(korean, Object.fromEntries(keys.map((key, i) => [key, match[i + 1]])));
  }
  return message;
}

export function translatePage(root = document) {
  document.documentElement.lang = language;
  for (const node of root.querySelectorAll('[data-i18n]')) node.textContent = tr(node.dataset.i18n);
  for (const attribute of ['aria-label', 'placeholder']) {
    for (const node of root.querySelectorAll(`[data-i18n-${attribute}]`)) {
      node.setAttribute(attribute, tr(node.getAttribute(`data-i18n-${attribute}`)));
    }
  }
}
