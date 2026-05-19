#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "..");
const tokensPath = path.join(root, "src", "theme", "tokens.ts");
const source = fs.readFileSync(tokensPath, "utf8");

function hexToRgb(hex) {
  const value = hex.replace("#", "");
  return {
    r: parseInt(value.slice(0, 2), 16) / 255,
    g: parseInt(value.slice(2, 4), 16) / 255,
    b: parseInt(value.slice(4, 6), 16) / 255
  };
}

function channel(value) {
  return value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
}

function luminance(hex) {
  const { r, g, b } = hexToRgb(hex);
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

function contrast(a, b) {
  const l1 = luminance(a);
  const l2 = luminance(b);
  const lighter = Math.max(l1, l2);
  const darker = Math.min(l1, l2);
  return (lighter + 0.05) / (darker + 0.05);
}

function collectAppearances(text) {
  const appearances = [];
  const regex = /"([^"]+)": defineAppearance\("[^"]+", "[^"]+", \{([\s\S]*?)\n  \}\),/g;
  let match;
  while ((match = regex.exec(text))) {
    const [, key, body] = match;
    const values = {};
    const colorRegex = /(\w+): "(#[0-9a-fA-F]{6})"/g;
    let colorMatch;
    while ((colorMatch = colorRegex.exec(body))) {
      values[colorMatch[1]] = colorMatch[2];
    }
    appearances.push({ key, values });
  }
  return appearances;
}

const checks = [
  ["text", "bg", 4.5],
  ["text", "shell", 4.5],
  ["text", "header", 4.5],
  ["textMuted", "bg", 3],
  ["textMuted", "shell", 3],
  ["blue", "bg", 3],
  ["green", "bg", 3],
  ["amber", "bg", 3],
  ["red", "bg", 3]
];

const failures = [];
for (const { key, values } of collectAppearances(source)) {
  for (const [fg, bg, minimum] of checks) {
    if (!values[fg] || !values[bg]) continue;
    const ratio = contrast(values[fg], values[bg]);
    if (ratio < minimum) {
      failures.push(`${key}: ${fg} on ${bg} = ${ratio.toFixed(2)}:1, expected ${minimum}:1`);
    }
  }
}

if (failures.length) {
  console.error("Accessibility contrast audit failed:");
  for (const failure of failures) console.error(`- ${failure}`);
  process.exit(1);
}

console.log("Accessibility contrast audit passed.");
