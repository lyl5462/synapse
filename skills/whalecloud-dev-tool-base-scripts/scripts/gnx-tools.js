#!/usr/bin/env node
/**
 * gnx-tools.js — 与 gitnexus-web Nexus（Backend 模式）对齐的 GitNexus REST 封装：
 * - 在线：cypher → POST /api/query，search → POST /api/search；overview / explore / impact 由固定 Cypher 组合实现。
 * - 本地缓存：materialize 将文件正文落盘到 --cache/files/；read / grep 仅读缓存，不再打 /api/file。
 *
 * 用法（均需 Node 18+，无第三方依赖）：
 *   node gnx-tools.js materialize --url http://HOST:11011 --repo REPO --cache ./gnx-cache [--concurrency 8] [--verbose] [--progress-every 40]
 *     （不加 --max-files 则默认不限制文件数量；仅在磁盘/网络受限时才临时加 --max-files N）
 *   node gnx-tools.js cypher      --url ... --repo ... --cypher "MATCH (n) RETURN n LIMIT 3"
 *   node gnx-tools.js search      --url ... --repo ... --query "auth" [--limit 10]
 *   node gnx-tools.js read        --cache ./gnx-cache --path src/Foo.cpp [--lines 80]
 *   node gnx-tools.js grep        --cache ./gnx-cache --pattern "TODO" [--glob "*.cpp"] [--max 80]
 *   node gnx-tools.js overview    --url ... --repo ... [--out ./overview.json]
 *   node gnx-tools.js explore     --url ... --repo ... --target "SymbolOrPath" [--type symbol|cluster|process]
 *   node gnx-tools.js impact      --url ... --repo ... --target "NameOrPath" --direction upstream|downstream [--depth 1]
 *
 * 环境变量：GITNEXUS_URL、GNX_REPO、GNX_CACHE（可替代对应 flag）
 */

'use strict';

const http = require('http');
const https = require('https');
const fs = require('fs');
const path = require('path');

function die(msg) {
  console.error(msg);
  process.exit(1);
}

function parseArgs(argv) {
  const out = { _: [] };
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    if (a.startsWith('--')) {
      const k = a.slice(2);
      const v = argv[i + 1] && !argv[i + 1].startsWith('--') ? argv[++i] : 'true';
      out[k.replace(/-/g, '_')] = v;
    } else out._.push(a);
  }
  return out;
}

function normalizeBaseUrl(raw) {
  let u = (raw || '').trim().replace(/\/+$/, '');
  if (!u) die('missing --url or GITNEXUS_URL');
  if (!/^https?:\/\//i.test(u)) u = 'http://' + u;
  return u;
}

function httpRequestJson(method, fullUrl, bodyObj, timeoutMs) {
  return new Promise((resolve, reject) => {
    const u = new URL(fullUrl);
    const lib = u.protocol === 'https:' ? https : http;
    const payload = bodyObj != null ? JSON.stringify(bodyObj) : null;
    const opts = {
      hostname: u.hostname,
      port: u.port || (u.protocol === 'https:' ? 443 : 80),
      path: u.pathname + u.search,
      method,
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
      },
    };
    const req = lib.request(opts, (res) => {
      let data = '';
      res.on('data', (c) => (data += c));
      res.on('end', () => {
        if (res.statusCode && res.statusCode >= 400) {
          reject(new Error(`HTTP ${res.statusCode}: ${data.slice(0, 500)}`));
          return;
        }
        try {
          resolve(JSON.parse(data));
        } catch {
          resolve({ _raw: data });
        }
      });
    });
    req.setTimeout(timeoutMs || 120000, () => {
      req.destroy(new Error('timeout'));
    });
    req.on('error', reject);
    if (payload) req.write(payload);
    req.end();
  });
}

function getJson(base, pathname, timeoutMs) {
  const url = new URL(pathname, base.endsWith('/') ? base : base + '/').toString();
  return httpRequestJson('GET', url, null, timeoutMs);
}

function postApi(base, subpath, body, timeoutMs) {
  const url = new URL(subpath, base.endsWith('/') ? base : base + '/').toString();
  return httpRequestJson('POST', url, body, timeoutMs);
}

function repoQ(repo) {
  return encodeURIComponent(repo);
}

async function cmdCypher(args) {
  const base = normalizeBaseUrl(args.url || process.env.GITNEXUS_URL);
  const repo = args.repo || process.env.GNX_REPO;
  const cypher = args.cypher || args.query;
  if (!repo || !cypher) die('cypher: need --repo and --cypher');
  const j = await postApi(base, '/api/query', { cypher, repo }, args.timeout ? +args.timeout : 120000);
  process.stdout.write(JSON.stringify(j, null, 2) + '\n');
}

async function cmdSearch(args) {
  const base = normalizeBaseUrl(args.url || process.env.GITNEXUS_URL);
  const repo = args.repo || process.env.GNX_REPO;
  const query = args.query || args.q;
  if (!repo || !query) die('search: need --repo and --query');
  const limit = Math.min(100, Math.max(1, parseInt(args.limit || '10', 10) || 10));
  const j = await postApi(base, '/api/search', { query, limit, repo }, args.timeout ? +args.timeout : 120000);
  process.stdout.write(JSON.stringify(j, null, 2) + '\n');
}

function safeCacheFile(cacheRoot, relPath) {
  const filesRoot = path.resolve(path.join(cacheRoot, 'files'));
  const norm = relPath.replace(/\\/g, '/').replace(/^\/+/, '');
  if (norm.includes('..')) die('read: illegal path');
  const full = path.resolve(path.join(filesRoot, norm));
  const sep = path.sep;
  if (full !== filesRoot && !full.startsWith(filesRoot + sep)) die('read: path escape');
  return full;
}

function cmdRead(args) {
  const cache = args.cache || process.env.GNX_CACHE;
  const p = args.path || args.file;
  if (!cache || !p) die('read: need --cache and --path');
  const full = safeCacheFile(cache, p);
  if (!fs.existsSync(full)) die(`read: not in cache: ${p}\nRun: node gnx-tools.js materialize ... (without --max-files to get all files)`);
  const content = fs.readFileSync(full, 'utf8');
  const lines = args.lines ? parseInt(args.lines, 10) : 0;
  if (lines > 0) {
    const truncated = content.split('\n').slice(0, lines).join('\n');
    process.stdout.write(truncated + (content.split('\n').length > lines ? '\n... (truncated, use --lines N to show more)\n' : '\n'));
  } else {
    process.stdout.write(content);
  }
}

function cmdGrep(args) {
  const cache = args.cache || process.env.GNX_CACHE;
  const pattern = args.pattern || args.p;
  if (!cache || !pattern) die('grep: need --cache and --pattern');
  const filesRoot = path.join(cache, 'files');
  if (!fs.existsSync(filesRoot)) die('grep: cache/files missing; run materialize first');
  let re;
  try {
    re = new RegExp(pattern, args.case ? '' : 'i');
  } catch (e) {
    die(`grep: bad regex: ${e.message}`);
  }
  const glob = (args.glob || '').toLowerCase();
  const max = Math.min(500, parseInt(args.max || '100', 10) || 100);
  const out = [];
  function walk(d) {
    for (const ent of fs.readdirSync(d, { withFileTypes: true })) {
      if (out.length >= max) return;
      const fp = path.join(d, ent.name);
      if (ent.isDirectory()) walk(fp);
      else {
        const rel = path.relative(filesRoot, fp).replace(/\\/g, '/');
        if (glob && !rel.toLowerCase().includes(glob.replace(/\*/g, ''))) continue;
        const txt = fs.readFileSync(fp, 'utf8');
        const lines = txt.split('\n');
        for (let i = 0; i < lines.length; i++) {
          if (out.length >= max) return;
          if (re.test(lines[i])) {
            out.push(`${rel}:${i + 1}:${lines[i].trim().slice(0, 200)}`);
            re.lastIndex = 0;
          }
        }
      }
    }
  }
  walk(filesRoot);
  process.stdout.write(out.join('\n') + (out.length ? '\n' : ''));
}

async function queryRows(base, repo, cypher) {
  const j = await postApi(base, '/api/query', { cypher, repo }, 120000);
  return j.result != null ? j.result : j;
}

async function cmdOverview(args) {
  const base = normalizeBaseUrl(args.url || process.env.GITNEXUS_URL);
  const repo = args.repo || process.env.GNX_REPO;
  if (!repo) die('overview: need --repo');
  const clustersQuery = `
MATCH (c:Community)
RETURN c.id AS id, c.label AS label, c.cohesion AS cohesion, c.symbolCount AS symbolCount, c.description AS description
ORDER BY c.symbolCount DESC
LIMIT 200`;
  const processesQuery = `
MATCH (p:Process)
RETURN p.id AS id, p.label AS label, p.processType AS type, p.stepCount AS stepCount, p.communities AS communities
ORDER BY p.stepCount DESC
LIMIT 200`;
  const depsQuery = `
MATCH (a)-[:CodeRelation {type: 'CALLS'}]->(b)
MATCH (a)-[:CodeRelation {type: 'MEMBER_OF'}]->(c1:Community)
MATCH (b)-[:CodeRelation {type: 'MEMBER_OF'}]->(c2:Community)
WHERE c1.id <> c2.id
RETURN c1.label AS \`from\`, c2.label AS \`to\`, COUNT(*) AS calls
ORDER BY calls DESC
LIMIT 15`;
  const criticalQuery = `
MATCH (s)-[r:CodeRelation {type: 'STEP_IN_PROCESS'}]->(p:Process)
RETURN p.label AS label, COUNT(r) AS steps
ORDER BY steps DESC
LIMIT 10`;
  const [clusters, processes, deps, critical] = await Promise.all([
    queryRows(base, repo, clustersQuery),
    queryRows(base, repo, processesQuery),
    queryRows(base, repo, depsQuery),
    queryRows(base, repo, criticalQuery),
  ]);
  const out = {
    tool: 'overview',
    repo,
    clusters,
    processes,
    clusterDependencies: deps,
    criticalProcesses: critical,
  };
  const json = JSON.stringify(out, null, 2) + '\n';
  const outPath = args.out || args.output;
  if (outPath) {
    const abs = path.isAbsolute(outPath) ? outPath : path.join(process.cwd(), outPath);
    fs.mkdirSync(path.dirname(abs), { recursive: true });
    fs.writeFileSync(abs, json, 'utf8');
    process.stderr.write(`overview: wrote ${abs}\n`);
  } else {
    // 在 PowerShell 中，直接用 > 重定向 stdout 会产生 UTF-16 BOM，导致下游脚本解析失败。
    // 强烈建议始终使用 --out <path> 参数，而非 > 重定向。
    process.stderr.write(
      `\n⚠  overview: --out 参数未指定，输出到 stdout。\n` +
      `   在 PowerShell 中使用 > 重定向会产生 UTF-16 BOM，导致 detect-project-kind.js 等脚本解析失败。\n` +
      `   建议改用：node gnx-tools.js overview --url ... --repo ... --out <CACHE_DIR>/overview.json\n\n`
    );
    process.stdout.write(json);
  }
}

async function cmdExplore(args) {
  const base = normalizeBaseUrl(args.url || process.env.GITNEXUS_URL);
  const repo = args.repo || process.env.GNX_REPO;
  const target = args.target || args.t;
  if (!repo || !target) die('explore: need --repo and --target');
  const esc = target.replace(/'/g, "''");
  const type = (args.type || '').toLowerCase();
  let cypher;
  if (type === 'cluster') {
    cypher = `MATCH (c:Community) WHERE c.label CONTAINS '${esc}' OR c.heuristicLabel CONTAINS '${esc}' RETURN c LIMIT 25`;
  } else if (type === 'process') {
    cypher = `MATCH (p:Process) WHERE p.label CONTAINS '${esc}' RETURN p LIMIT 25`;
  } else {
    cypher = `MATCH (n) WHERE n.name IS NOT NULL AND toString(n.name) CONTAINS '${esc}' RETURN labels(n) AS labels, n.name AS name, n.filePath AS filePath, n.id AS id LIMIT 40`;
  }
  const rows = await queryRows(base, repo, cypher);
  process.stdout.write(JSON.stringify({ tool: 'explore', target, type: type || 'auto', rows }, null, 2) + '\n');
}

async function cmdImpact(args) {
  const base = normalizeBaseUrl(args.url || process.env.GITNEXUS_URL);
  const repo = args.repo || process.env.GNX_REPO;
  const target = args.target || args.t;
  const direction = (args.direction || 'downstream').toLowerCase();
  if (!repo || !target) die('impact: need --repo and --target');
  if (direction !== 'upstream' && direction !== 'downstream') die('impact: --direction upstream|downstream');
  const depth = Math.min(3, Math.max(1, parseInt(args.depth || '1', 10) || 1));
  const esc = target.replace(/'/g, "''");
  const isPath = target.includes('/') || target.includes('\\');
  const findQ = isPath
    ? `MATCH (n) WHERE n.filePath IS NOT NULL AND n.filePath CONTAINS '${esc}' RETURN n.id AS id, labels(n) AS labels, n.filePath AS filePath LIMIT 15`
    : `MATCH (n) WHERE n.name = '${esc}' RETURN n.id AS id, labels(n) AS labels, n.filePath AS filePath LIMIT 15`;
  const found = await queryRows(base, repo, findQ);
  const out = { tool: 'impact', target, direction, depth, find: found };
  if (!found || !found.length) {
    process.stdout.write(JSON.stringify(out, null, 2) + '\n');
    return;
  }
  const row0 = found[0];
  const id = row0.id != null ? row0.id : row0[0];
  const labels = row0.labels != null ? row0.labels : row0[1];
  const _nodeLabel = Array.isArray(labels) ? labels[0] : String(labels || 'Function');
  const rels = `['CALLS','IMPORTS','EXTENDS','IMPLEMENTS']`;
  let hopQ;
  if (direction === 'upstream') {
    hopQ = `
MATCH (n {id: '${String(id).replace(/'/g, "''")}'})
MATCH (src)-[r:CodeRelation]->(n)
WHERE r.type IN ${rels}
RETURN DISTINCT labels(src)[0] AS srcLabel, src.name AS srcName, src.filePath AS srcPath, type(r) AS relType, r.type AS codeRelType
LIMIT 120`;
  } else {
    hopQ = `
MATCH (n {id: '${String(id).replace(/'/g, "''")}'})
MATCH (n)-[r:CodeRelation]->(dst)
WHERE r.type IN ${rels}
RETURN DISTINCT labels(dst)[0] AS dstLabel, dst.name AS dstName, dst.filePath AS dstPath, type(r) AS relType, r.type AS codeRelType
LIMIT 120`;
  }
  if (depth >= 1) out.neighbors = await queryRows(base, repo, hopQ);
  process.stdout.write(JSON.stringify(out, null, 2) + '\n');
}

async function httpGetText(fullUrl, timeoutMs) {
  return new Promise((resolve, reject) => {
    const u = new URL(fullUrl);
    const lib = u.protocol === 'https:' ? https : http;
    const req = lib.get(
      {
        hostname: u.hostname,
        port: u.port || (u.protocol === 'https:' ? 443 : 80),
        path: u.pathname + u.search,
        headers: { Accept: 'application/json' },
      },
      (res) => {
        let data = '';
        res.on('data', (c) => (data += c));
        res.on('end', () => {
          if (res.statusCode && res.statusCode >= 400) {
            reject(new Error(`HTTP ${res.statusCode}: ${data.slice(0, 300)}`));
          } else resolve(data);
        });
      },
    );
    req.setTimeout(timeoutMs || 600000, () => req.destroy(new Error('timeout')));
    req.on('error', reject);
  });
}

async function cmdMaterialize(args) {
  const base = normalizeBaseUrl(args.url || process.env.GITNEXUS_URL);
  const repo = args.repo || process.env.GNX_REPO;
  const cache = args.cache || process.env.GNX_CACHE;
  if (!repo || !cache) die('materialize: need --repo and --cache');
  const rawMaxFiles = parseInt(args.max_files || '0', 10);
  const maxFiles = rawMaxFiles > 0 ? Math.min(rawMaxFiles, 200000) : Infinity;
  const concurrency = Math.min(32, Math.max(1, parseInt(args.concurrency || '8', 10) || 8));
  const verbose = args.verbose === 'true' || args.verbose === true || args.v === 'true' || args.v === true;
  const progressEvery = Math.max(1, parseInt(args.progress_every || args.progressEvery || '40', 10) || 40);
  const filesRoot = path.join(cache, 'files');
  fs.mkdirSync(filesRoot, { recursive: true });
  const manifest = { repo, url: base, fileCount: 0, errors: [] };
  const limitClause = isFinite(maxFiles) ? `LIMIT ${maxFiles}` : '';
  const filesCypher = `MATCH (f:File) WHERE f.filePath IS NOT NULL RETURN f.filePath AS filePath ${limitClause}`.trim();
  if (verbose) process.stderr.write(`materialize: Cypher query: ${filesCypher}\n`);
  const rows = await queryRows(base, repo, filesCypher);
  const filePaths = rows.map(r => r.filePath || r[0]).filter(Boolean);
  if (verbose) process.stderr.write(`materialize: found ${filePaths.length} files, fetching content via /api/file\n`);

  async function fetchOne(fp) {
    const u = `${base}/api/file?repo=${repoQ(repo)}&path=${encodeURIComponent(fp)}`;
    const txt = await httpGetText(u, 60000);
    let j;
    try {
      j = JSON.parse(txt);
    } catch {
      return null;
    }
    return j.content != null ? String(j.content) : null;
  }

  let written = 0;
  let fetchAttempt = 0;
  const totalFetch = filePaths.length;
  if (verbose && totalFetch) {
    process.stderr.write(`materialize: /api/file phase ${totalFetch} paths, concurrency=${concurrency}\n`);
  }
  for (let i = 0; i < filePaths.length && written < maxFiles; i += concurrency) {
    const chunk = filePaths.slice(i, i + concurrency);
    const results = await Promise.all(
      chunk.map(async (fp) => {
        if (!fp) return { fp: null, ok: false };
        try {
          const c = await fetchOne(fp);
          return { fp, content: c, err: null };
        } catch (e) {
          return { fp, content: null, err: String(e.message || e) };
        }
      }),
    );
    for (const r of results) {
      if (written >= maxFiles) break;
      if (!r.fp) continue;
      fetchAttempt++;
      if (r.err) {
        manifest.errors.push({ path: r.fp, error: r.err });
        continue;
      }
      if (r.content == null) continue;
      try {
        const full = safeCacheFile(cache, r.fp);
        fs.mkdirSync(path.dirname(full), { recursive: true });
        fs.writeFileSync(full, r.content, 'utf8');
        written++;
        if (verbose && fetchAttempt % progressEvery === 0) {
          process.stderr.write(`materialize: /api/file progress ${fetchAttempt}/${totalFetch} tried, ${written} written\n`);
        }
      } catch (e) {
        manifest.errors.push({ path: r.fp, error: String(e.message || e) });
      }
    }
  }

  manifest.fileCount = written;
  fs.mkdirSync(cache, { recursive: true });
  fs.writeFileSync(path.join(cache, 'manifest.json'), JSON.stringify(manifest, null, 2), 'utf8');
  process.stderr.write(`materialize: wrote ${written} files under ${path.join(cache, 'files')}\n`);
}

function printHelp() {
  console.log(`gnx-tools — GitNexus REST 七工具封装（与 gitnexus-web Backend 同源 /api/query + /api/search）

子命令: materialize | cypher | search | read | grep | overview | explore | impact

示例见 ../references/README-GNX-TOOLS.md`);
}

async function main() {
  const cmd = process.argv[2];
  const args = parseArgs(process.argv);
  if (!cmd || cmd === '-h' || cmd === '--help') {
    printHelp();
    process.exit(0);
  }
  try {
    switch (cmd) {
      case 'materialize':
        await cmdMaterialize(args);
        break;
      case 'cypher':
        await cmdCypher(args);
        break;
      case 'search':
        await cmdSearch(args);
        break;
      case 'read':
        cmdRead(args);
        break;
      case 'grep':
        cmdGrep(args);
        break;
      case 'overview':
        await cmdOverview(args);
        break;
      case 'explore':
        await cmdExplore(args);
        break;
      case 'impact':
        await cmdImpact(args);
        break;
      default:
        printHelp();
        die(`unknown command: ${cmd}`);
    }
  } catch (e) {
    die(String(e.message || e));
  }
}

main();
