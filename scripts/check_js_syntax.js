#!/usr/bin/env node
/** 发版门禁：node --check 校验 web/static/js 下全部业务脚本（在 node:20-alpine 容器内运行）。 */
const fs = require("fs");
const path = require("path");
const { spawnSync } = require("child_process");

const jsDir = path.join(__dirname, "..", "web", "static", "js");
const files = fs.readdirSync(jsDir).filter((f) => f.endsWith(".js")).sort();

if (!files.length) {
  console.error("ERROR: no JS files in", jsDir);
  process.exit(1);
}

for (const f of files) {
  const p = path.join(jsDir, f);
  process.stdout.write(`checking ${p}\n`);
  const r = spawnSync(process.execPath, ["--check", p], { stdio: "inherit" });
  if (r.status) process.exit(r.status || 1);
}

console.log(`OK  node --check (${files.length} files)`);
