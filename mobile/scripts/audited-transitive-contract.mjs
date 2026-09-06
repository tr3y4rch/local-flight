import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const mobileRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');

const readPackageVersion = (name) =>
  JSON.parse(
    readFileSync(resolve(mobileRoot, 'node_modules', name, 'package.json'), 'utf8'),
  ).version;

const expectedVersions = {
  'query-string': '9.5.1',
  'decode-uri-component': '0.5.0',
  uuid: '11.1.1',
};

for (const [name, expected] of Object.entries(expectedVersions)) {
  const actual = readPackageVersion(name);
  if (actual !== expected) {
    throw new Error(`${name} must resolve to ${expected}; found ${actual}`);
  }
}

const navigationFiles = [
  'src/getPathFromState.tsx',
  'src/getStateFromPath.tsx',
  'lib/module/getPathFromState.js',
  'lib/module/getStateFromPath.js',
];

for (const relativePath of navigationFiles) {
  const source = readFileSync(
    resolve(mobileRoot, 'node_modules/@react-navigation/core', relativePath),
    'utf8',
  );
  if (!source.includes("import queryString from 'query-string';")) {
    throw new Error(`Missing audited query-string compatibility patch: ${relativePath}`);
  }
}

const queryString = (await import('query-string')).default;
const parsed = queryString.parse(
  'screen=Board&airport=JFK&flag&repeat=1&repeat=2',
);
const encoded = queryString.stringify({
  screen: 'Board',
  airport: 'JFK',
  repeat: ['1', '2'],
});

if (
  parsed.screen !== 'Board' ||
  parsed.airport !== 'JFK' ||
  parsed.flag !== null ||
  parsed.repeat?.length !== 2 ||
  encoded !== 'airport=JFK&repeat=1&repeat=2&screen=Board'
) {
  throw new Error('query-string navigation compatibility check failed');
}

const xcode = require('xcode');
const project = xcode.project('/tmp/localflight-audit-contract/project.pbxproj');
project.hash = { project: { objects: {} } };
const firstUuid = project.generateUuid();
const secondUuid = project.generateUuid();
if (!/^[A-F0-9]{24}$/.test(firstUuid) || firstUuid === secondUuid) {
  throw new Error('xcode UUID generation compatibility check failed');
}

console.log('Audited mobile transitive dependency contracts passed.');
