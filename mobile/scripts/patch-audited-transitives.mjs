import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const mobileRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const targets = [
  'node_modules/@react-navigation/core/src/getPathFromState.tsx',
  'node_modules/@react-navigation/core/src/getStateFromPath.tsx',
  'node_modules/@react-navigation/core/lib/module/getPathFromState.js',
  'node_modules/@react-navigation/core/lib/module/getStateFromPath.js',
];

const oldImport = "import * as queryString from 'query-string';";
const safeImport = "import queryString from 'query-string';";

for (const relativePath of targets) {
  const path = resolve(mobileRoot, relativePath);
  const source = readFileSync(path, 'utf8');

  if (source.includes(safeImport)) {
    continue;
  }

  if (!source.includes(oldImport)) {
    throw new Error(
      `Refusing to patch unexpected React Navigation source: ${relativePath}`,
    );
  }

  writeFileSync(path, source.replace(oldImport, safeImport));
}

console.log(
  'React Navigation uses the audited query-string default export compatibility patch.',
);
