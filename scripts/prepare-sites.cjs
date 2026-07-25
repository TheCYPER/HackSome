"use strict";

const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const output = path.join(root, "public");
const files = [
  "index.html",
  "join.html",
  "styles.css",
  "companion.css",
  "app.js",
  "join.js",
  "safety-policy.js",
  "outcome-model.js",
  "manifest.webmanifest",
  "sw.js",
];

fs.mkdirSync(output, { recursive: true });
for (const file of files) fs.copyFileSync(path.join(root, file), path.join(output, file));
fs.cpSync(path.join(root, "assets"), path.join(output, "assets"), { recursive: true, force: true });
console.log(`Prepared ${files.length} public review files and assets for Sites.`);
