#!/usr/bin/env node
/**
 * 依据 materialize 缓存下的文件扩展名 + 关键构建文件名，推断工程类型（与 SKILL Phase 0.1 对齐）。
 * 可选传入 overview.json（gnx-tools overview 输出）仅作附加信号（Community 标签等）。
 *
 * 用法:
 *   node detect-project-kind.js --cache ./gnx-cache [--overview ./gnx-cache/overview.json]
 *
 * 输出: 一行 JSON 到 stdout，含 kind / confidence / signals
 */
'use strict';

const fs = require('fs');
const path = require('path');

function die(m) {
  console.error(m);
  process.exit(1);
}

function parseArgs(argv) {
  const o = {};
  for (let i = 2; i < argv.length; i++) {
    if (argv[i] === '--cache') o.cache = argv[++i];
    else if (argv[i] === '--overview') o.overview = argv[++i];
  }
  return o;
}

/**
 * Read JSON from disk tolerating UTF-8 BOM and PowerShell-default UTF-16 LE redirects.
 */
function readJsonFileRobust(filePath) {
  const buf = fs.readFileSync(filePath);
  if (buf.length >= 2 && buf[0] === 0xff && buf[1] === 0xfe) {
    return JSON.parse(buf.slice(2).toString('utf16le'));
  }
  if (buf.length >= 3 && buf[0] === 0xef && buf[1] === 0xbb && buf[2] === 0xbf) {
    return JSON.parse(buf.slice(3).toString('utf8'));
  }
  return JSON.parse(buf.toString('utf8'));
}

function walkFiles(root, acc, max = 8000) {
  if (!fs.existsSync(root)) return;
  let n = 0;
  function w(d) {
    for (const ent of fs.readdirSync(d, { withFileTypes: true })) {
      if (n >= max) return;
      const p = path.join(d, ent.name);
      if (ent.isDirectory()) w(p);
      else {
        acc.push(p);
        n++;
      }
    }
  }
  w(root);
}

function main() {
  const args = parseArgs(process.argv);
  if (!args.cache) die('need --cache (materialize output dir with files/)');
  const filesRoot = path.join(args.cache, 'files');
  if (!fs.existsSync(filesRoot)) die('cache/files not found; run gnx-tools.js materialize first');

  const files = [];
  walkFiles(filesRoot, files);

  const extCount = {};
  const baseNames = {};
  for (const fp of files) {
    const ext = (path.extname(fp) || '(noext)').toLowerCase();
    extCount[ext] = (extCount[ext] || 0) + 1;
    baseNames[path.basename(fp).toLowerCase()] = true;
  }

  const n = (ext) => extCount[ext] || 0;
  const cppLike = n('.cpp') + n('.cc') + n('.cxx') + n('.c') + n('.h') + n('.hpp') + n('.hh');
  const py = n('.py');
  const js = n('.js') + n('.mjs') + n('.cjs');
  const ts = n('.ts') + n('.tsx');
  const java = n('.java') + n('.kt');
  const go = n('.go');
  const rs = n('.rs');
  const cs = n('.cs');

  const signals = [];
  const has = (name) => !!baseNames[name];

  if (has('cmakelists.txt')) signals.push('marker:CMakeLists.txt');
  if (has('makefile') || has('makefile.incl')) signals.push('marker:Makefile');
  if (has('package.json')) signals.push('marker:package.json');
  if (has('go.mod')) signals.push('marker:go.mod');
  if (has('cargo.toml')) signals.push('marker:Cargo.toml');
  if (has('pom.xml') || has('build.gradle') || has('build.gradle.kts')) signals.push('marker:jvm-build');
  if (files.some((f) => f.toLowerCase().endsWith('.csproj'))) signals.push('marker:dotnet');
  if (has('pyproject.toml') || has('requirements.txt')) signals.push('marker:python-packaging');

  let kind = 'mixed_polyglot';
  let confidence = 0.35;

  const total = Object.values(extCount).reduce((a, b) => a + b, 0) || 1;

  if (has('go.mod') && go > total * 0.05) {
    kind = 'go';
    confidence = 0.75;
  } else if (has('cargo.toml') && rs > total * 0.05) {
    kind = 'rust';
    confidence = 0.78;
  } else if ((has('pom.xml') || has('build.gradle')) && java > total * 0.08) {
    kind = 'jvm';
    confidence = 0.72;
  } else if (files.some((f) => f.toLowerCase().endsWith('.csproj')) && cs > total * 0.08) {
    kind = 'dotnet';
    confidence = 0.72;
  } else if ((has('pyproject.toml') || has('requirements.txt')) && py > cppLike && py > total * 0.1) {
    kind = 'python';
    confidence = 0.7;
  } else if (has('package.json') && ts + js > cppLike && ts + js > total * 0.12) {
    kind = 'node_ts';
    confidence = 0.68;
  } else if (cppLike > total * 0.25 && (has('cmakelists.txt') || has('makefile') || has('makefile.incl'))) {
    kind = 'cpp_native';
    confidence = Math.min(0.92, 0.55 + cppLike / total);
    signals.push(`ratio:cppLike=${(cppLike / total).toFixed(2)}`);
  } else if (cppLike > total * 0.15 && py + js + ts > total * 0.08) {
    kind = 'cpp_mixed';
    confidence = 0.55;
  } else if (py > total * 0.2) {
    kind = 'python';
    confidence = 0.55;
  } else if (ts + js > total * 0.2) {
    kind = 'node_ts';
    confidence = 0.52;
  } else {
    signals.push('fallback:weak-dominance');
  }

  if (args.overview && fs.existsSync(args.overview)) {
    try {
      const ov = readJsonFileRobust(args.overview);
      const n = Array.isArray(ov.clusters) ? ov.clusters.length : 0;
      if (n) signals.push(`overview:clusters=${n}`);
      const np = Array.isArray(ov.processes) ? ov.processes.length : 0;
      if (np) signals.push(`overview:processes=${np}`);
      if (!n && !np) signals.push('overview:empty-clusters-and-processes');
    } catch (e) {
      signals.push(`overview:parse-failed:${String(e.message || e).slice(0, 80)}`);
    }
  }

  const out = {
    projectKind: kind,
    confidence,
    signals,
    extHistogramTop: Object.entries(extCount)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 14)
      .map(([ext, c]) => ({ ext, count: c })),
    scannedFileCount: files.length,
  };
  process.stdout.write(JSON.stringify(out, null, 2) + '\n');
}

main();
