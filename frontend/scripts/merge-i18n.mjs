// One-off helper: merges a flat {"a.b.c": {en, pt, es}} map into the three
// locale JSON files at the given nested path, creating objects as needed.
// Usage: node scripts/merge-i18n.mjs path/to/entries.json
import fs from 'node:fs';

const entriesPath = process.argv[2];
if (!entriesPath) {
  console.error('Usage: node merge-i18n.mjs <entries.json>');
  process.exit(1);
}

const entries = JSON.parse(fs.readFileSync(entriesPath, 'utf8'));
const localesDir = new URL('../src/locales/', import.meta.url);

for (const lang of ['en', 'pt', 'es']) {
  const filePath = new URL(`${lang}.json`, localesDir);
  const data = JSON.parse(fs.readFileSync(filePath, 'utf8'));
  for (const [key, translations] of Object.entries(entries)) {
    const parts = key.split('.');
    let node = data;
    for (let i = 0; i < parts.length - 1; i++) {
      const part = parts[i];
      if (typeof node[part] !== 'object' || node[part] === null) node[part] = {};
      node = node[part];
    }
    const leaf = parts[parts.length - 1];
    if (!(lang in translations)) {
      console.warn(`Missing "${lang}" translation for key "${key}" — skipping`);
      continue;
    }
    node[leaf] = translations[lang];
  }
  fs.writeFileSync(filePath, JSON.stringify(data, null, 2) + '\n');
}
console.log(`Merged ${Object.keys(entries).length} keys into en/pt/es.json`);
