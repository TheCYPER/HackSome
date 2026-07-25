"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const projectRoot = path.resolve(__dirname, "..");
const distPath = path.join(projectRoot, "dist");

if (path.dirname(distPath) !== projectRoot || path.basename(distPath) !== "dist") {
  throw new Error(`Refusing to clean unexpected build path: ${distPath}`);
}

if (fs.existsSync(distPath)) {
  const result = spawnSync("/bin/rm", ["-rf", "--", distPath], {
    cwd: projectRoot,
    encoding: "utf8",
  });
  if (result.status !== 0 || fs.existsSync(distPath)) {
    throw new Error(`Unable to clean generated build directory: ${result.stderr || "path still exists"}`);
  }
}
