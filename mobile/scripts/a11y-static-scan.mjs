#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "..");
const srcRoot = path.join(root, "src");
const targets = [];

function walk(dir) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      walk(full);
    } else if (/\.(tsx|ts)$/.test(entry.name)) {
      targets.push(full);
    }
  }
}

walk(srcRoot);

const warnings = [];
for (const file of targets) {
  if (file.includes(`${path.sep}accessibility${path.sep}`)) continue;
  const text = fs.readFileSync(file, "utf8");
  let offset = 0;
  while (true) {
    const start = text.indexOf("<Pressable", offset);
    if (start === -1) break;
    let end = start;
    while (end < text.length) {
      if (text[end] === ">" && text[end - 1] !== "=") break;
      end += 1;
    }
    const block = text.slice(start, end + 1);
    if (
      block.includes("accessibilityLabel") ||
      block.includes("accessibleButton(") ||
      block.includes("accessibilityRole=\"tab\"") ||
      block.includes("accessible={false}")
    ) {
      offset = end + 1;
      continue;
    }
    const before = text.slice(0, start);
    const line = before.split("\n").length;
    warnings.push(`${path.relative(root, file)}:${line}`);
    offset = end + 1;
  }
}

if (warnings.length) {
  console.warn(`Accessibility static scan found ${warnings.length} Pressable candidates without explicit labels.`);
  for (const warning of warnings.slice(0, 80)) console.warn(`- ${warning}`);
  if (warnings.length > 80) console.warn(`- ... ${warnings.length - 80} more`);
  console.warn("This scan is advisory because some wrappers inherit labels from reusable components.");
} else {
  console.log("Accessibility static scan passed: all Pressable candidates have explicit labels.");
}
