#!/usr/bin/env node
/**
 * fetch-arch-data.js
 *
 * Collects architecture-relevant data from a GitNexus instance started with
 * `gitnexus serve`: REST under /api/* and MCP Streamable HTTP at /api/mcp.
 *
 * Usage:
 *   node fetch-arch-data.js --url <GITNEXUS_URL> --repo <REPO_NAME> [options]
 *
 * Options:
 *   --url          <url>   GitNexus server base URL (required), e.g. http://127.0.0.1:11011
 *   --repo         <name>  Repository name as indexed (required)
 *   --out          <path>  Output file path (default: ./arch-data.json)
 *   --list                 List available repos and exit
 *   --with-snippets        MCP query() with include_content:true (smaller limits; heavier payload)
 *   --scan-source  <path>  Workspace root to scan for source files (enables Phase 1b pre-scan)
 *   --timeout      <ms>    Per-request timeout in ms (default: 30000)
 *   --debug                Print raw responses to stderr
 *   --debug-dump   <dir>   Write raw REST bodies + MCP SSE bodies to <dir> for diffing (UTF-8)
 *   --merge-overview <path>  When REST /api/clusters|processes returns empty arrays, load clusters/processes from this gnx-tools overview JSON
 *   --no-auto-overview     Disable auto-pick of <dirname(--out)>/overview.json when REST lists are empty
 *
 * Environment variables (override CLI flags):
 *   GITNEXUS_URL      Server URL
 *   REPO_ROOT         Workspace root for source scanning (same as --scan-source)
 *
 * Overview merge (1.5.0+): if REST cluster/process lists are empty, load gnx-tools overview JSON
 * (default: dirname(--out)/overview.json; override with --merge-overview; disable with --no-auto-overview).
 */

'use strict';

const https = require('https');
const http  = require('http');
const path  = require('path');
const fs    = require('fs');

// ─── Argument parsing ────────────────────────────────────────────────────────

function parseArgs(argv) {
  const args = {
    timeout: 30000,
    out: 'arch-data.json',
    debug: false,
    withSnippets: false,
    scanSource: null,
    debugDump: null,
    mergeOverview: null,
    noAutoOverview: false,
  };
  for (let i = 0; i < argv.length; i++) {
    switch (argv[i]) {
      case '--url':          args.url        = argv[++i]; break;
      case '--repo':         args.repo       = argv[++i]; break;
      case '--out':          args.out        = argv[++i]; break;
      case '--timeout':      args.timeout    = parseInt(argv[++i], 10); break;
      case '--list':         args.list       = true; break;
      case '--debug':        args.debug      = true; break;
      case '--with-snippets': args.withSnippets = true; break;
      case '--scan-source':  args.scanSource = argv[++i]; break;
      case '--debug-dump':   args.debugDump  = argv[++i]; break;
      case '--merge-overview': args.mergeOverview = argv[++i]; break;
      case '--no-auto-overview': args.noAutoOverview = true; break;
    }
  }
  if (process.env.GITNEXUS_URL) args.url        = args.url        || process.env.GITNEXUS_URL;
  if (process.env.REPO_ROOT)    args.scanSource = args.scanSource || process.env.REPO_ROOT;
  return args;
}

// ─── URL / HTTP helpers ──────────────────────────────────────────────────────

function defaultPort(protocol, portStr) {
  if (portStr !== undefined && portStr !== null && String(portStr) !== '') {
    return parseInt(String(portStr), 10);
  }
  return protocol === 'https:' ? 443 : 80;
}

function apiMcpPath(baseUrl) {
  const root = new URL(baseUrl.endsWith('/') ? baseUrl : baseUrl + '/');
  return new URL('api/mcp', root).pathname;
}

/**
 * Performs an HTTP(S) GET and returns parsed JSON.
 */
/**
 * GET 返回原始 UTF-8 字符串（不重定向跟随；用于 debug-dump）。
 */
function httpGetRaw(url, timeout) {
  return new Promise((resolve, reject) => {
    const parsed    = new URL(url);
    const transport = parsed.protocol === 'https:' ? https : http;
    const headers   = { Accept: 'application/json' };
    const port      = defaultPort(parsed.protocol, parsed.port);

    const req = transport.get(
      {
        hostname: parsed.hostname,
        port,
        path:     parsed.pathname + parsed.search,
        headers,
      },
      (res) => {
        if (res.statusCode === 301 || res.statusCode === 302) {
          const loc = res.headers.location;
          if (!loc) return reject(new Error('redirect without Location'));
          const nextUrl = /^https?:/i.test(loc) ? loc : new URL(loc, url).href;
          return httpGetRaw(nextUrl, timeout).then(resolve).catch(reject);
        }
        let body = '';
        res.setEncoding('utf8');
        res.on('data', d => { body += d; });
        res.on('end', () => {
          resolve({ statusCode: res.statusCode, headers: res.headers, body });
        });
      }
    );
    req.setTimeout(timeout, () => { req.destroy(new Error(`Timeout fetching ${url}`)); });
    req.on('error', reject);
  });
}

function httpGet(url, timeout, debug) {
  return new Promise((resolve, reject) => {
    const parsed    = new URL(url);
    const transport = parsed.protocol === 'https:' ? https : http;
    const headers   = { Accept: 'application/json' };
    const port      = defaultPort(parsed.protocol, parsed.port);

    const req = transport.get(
      {
        hostname: parsed.hostname,
        port,
        path:     parsed.pathname + parsed.search,
        headers,
      },
      (res) => {
        if (res.statusCode === 301 || res.statusCode === 302) {
          return httpGet(res.headers.location, timeout, debug).then(resolve).catch(reject);
        }
        if (res.statusCode === 404) return reject(new Error(`404 Not Found: ${url}`));
        if (res.statusCode >= 400)  return reject(new Error(`HTTP ${res.statusCode}: ${url}`));

        let body = '';
        res.on('data', d => { body += d; });
        res.on('end', () => {
          if (debug) process.stderr.write(`[debug] GET ${url}\n${body.slice(0, 400)}\n`);
          try { resolve(JSON.parse(body)); }
          catch { resolve({ _raw: body }); }
        });
      }
    );

    req.setTimeout(timeout, () => { req.destroy(new Error(`Timeout fetching ${url}`)); });
    req.on('error', reject);
  });
}

function headerOne(resHeaders, name) {
  const v = resHeaders[name.toLowerCase()];
  if (Array.isArray(v)) return v[0];
  return v;
}

/**
 * POST JSON to GitNexus MCP Streamable HTTP endpoint (/api/mcp).
 */
function mcpPost(baseUrl, timeout, debug, rpcObj, sessionOpts, mcpDump) {
  return new Promise((resolve, reject) => {
    const root = new URL(baseUrl.endsWith('/') ? baseUrl : baseUrl + '/');
    const transport = root.protocol === 'https:' ? https : http;
    const pathname = apiMcpPath(baseUrl);
    const body = JSON.stringify(rpcObj);
    const headers = {
      'Content-Type': 'application/json',
      Accept:         'application/json, text/event-stream',
      'Content-Length': Buffer.byteLength(body),
    };
    if (sessionOpts && sessionOpts.sessionId) {
      headers['mcp-session-id'] = sessionOpts.sessionId;
    }
    if (sessionOpts && sessionOpts.protocolVersion) {
      headers['mcp-protocol-version'] = sessionOpts.protocolVersion;
    }

    const req = transport.request(
      {
        hostname: root.hostname,
        port:     defaultPort(root.protocol, root.port),
        path:     pathname,
        method:   'POST',
        headers,
      },
      (res) => {
        const chunks = [];
        res.on('data', (c) => chunks.push(c));
        res.on('end', () => {
          const raw = Buffer.concat(chunks).toString('utf8');
          if (debug) {
            process.stderr.write(`[debug] MCP POST ${pathname} -> ${res.statusCode}\n${raw.slice(0, 600)}\n`);
          }
          if (mcpDump && mcpDump.dir && mcpDump.tag) {
            const tag = String(mcpDump.tag).replace(/[^a-zA-Z0-9_-]+/g, '_');
            writeDebugFile(mcpDump.dir, `mcp_${tag}_http_${res.statusCode}.sse.txt`, raw);
          }
          resolve({
            statusCode: res.statusCode,
            body:       raw,
            sessionId:  headerOne(res.headers, 'mcp-session-id'),
          });
        });
      }
    );
    req.setTimeout(timeout, () => req.destroy(new Error('MCP request timeout')));
    req.on('error', reject);
    req.write(body);
    req.end();
  });
}

function parseSseJsonMessages(bodyText) {
  const messages = [];
  if (!bodyText) return messages;
  const blocks = bodyText.split(/\r?\n\r?\n/);
  for (const block of blocks) {
    const lines = block.split(/\r?\n/).filter(Boolean);
    let dataLine = null;
    for (const line of lines) {
      if (line.startsWith('data:')) {
        const v = line.slice(5).trim();
        if (v !== '') dataLine = v;
      }
    }
    if (!dataLine) continue;
    try {
      messages.push(JSON.parse(dataLine));
    } catch (_) { /* ignore */ }
  }
  return messages;
}

function findRpcResult(messages, id) {
  for (const m of messages) {
    if (!m || m.id !== id) continue;
    if (m.error) {
      const msg = m.error.message || JSON.stringify(m.error);
      throw new Error(msg);
    }
    if (m.result !== undefined) return m.result;
  }
  return undefined;
}

function ensureDebugDumpDir(dir) {
  if (!dir) return null;
  const abs = path.isAbsolute(dir) ? dir : path.join(process.cwd(), dir);
  fs.mkdirSync(abs, { recursive: true });
  return abs;
}

function writeDebugFile(dumpDir, name, content) {
  if (!dumpDir) return;
  const safe = String(name).replace(/[^a-zA-Z0-9_.-]+/g, '_');
  fs.writeFileSync(path.join(dumpDir, safe), content, 'utf8');
}

function writeDebugJson(dumpDir, name, obj) {
  if (!dumpDir || obj == null) return;
  try {
    writeDebugFile(dumpDir, name, JSON.stringify(obj, null, 2));
  } catch (e) {
    writeDebugFile(dumpDir, `${name}.stringify-error.txt`, String(e));
  }
}

async function restGetWithOptionalDump(url, timeout, debug, dumpDir, dumpBaseName) {
  if (!dumpDir) {
    return httpGet(url, timeout, debug);
  }
  const raw = await httpGetRaw(url, timeout);
  writeDebugFile(dumpDir, `${dumpBaseName}.http.txt`,
    `status: ${raw.statusCode}\nurl: ${url}\n\n${raw.body}`);
  if (raw.statusCode >= 400) {
    throw new Error(`HTTP ${raw.statusCode}: ${url}`);
  }
  try {
    const parsed = JSON.parse(raw.body);
    writeDebugJson(dumpDir, `${dumpBaseName}.json`, parsed);
    return parsed;
  } catch (e) {
    writeDebugFile(dumpDir, `${dumpBaseName}.parse-error.txt`, String(e.message) + '\n' + raw.body.slice(0, 8000));
    return { _raw: raw.body };
  }
}

function parseToolResultText(text) {
  if (!text || typeof text !== 'string') return null;
  const cut = text.split(/\n\n---/)[0].trim();
  try {
    return JSON.parse(cut);
  } catch {
    return { _parseError: true, _rawPreview: text.slice(0, 2000) };
  }
}

/**
 * One-shot MCP session: initialize → notifications/initialized → tools/call(query).
 */
async function mcpQueryTool(baseUrl, timeout, debug, repo, queryText, queryOpts = {}, mcpDump = null) {
  const limit = queryOpts.limit ?? 8;
  const maxSymbols = queryOpts.max_symbols ?? 8;
  const includeContent = queryOpts.include_content === true;

  const initRes = await mcpPost(
    baseUrl,
    timeout,
    debug,
    {
      jsonrpc: '2.0',
      id:      0,
      method:  'initialize',
      params: {
        protocolVersion: '2025-11-25',
        capabilities:    {},
        clientInfo:      { name: 'fetch-arch-data', version: '1.2.0' },
      },
    },
    null,
    mcpDump ? { dir: mcpDump.dir, tag: `${mcpDump.queryTag}_initialize` } : null
  );

  if (initRes.statusCode !== 200) {
    throw new Error(`MCP initialize HTTP ${initRes.statusCode}: ${initRes.body.slice(0, 200)}`);
  }
  if (!initRes.sessionId) {
    throw new Error('MCP initialize: missing mcp-session-id response header');
  }

  const initMessages = parseSseJsonMessages(initRes.body);
  const initResult = findRpcResult(initMessages, 0);
  if (!initResult) {
    throw new Error('MCP initialize: no JSON-RPC result in SSE body');
  }
  const protocolVersion = initResult.protocolVersion || '2025-03-26';
  const sessionOpts = { sessionId: initRes.sessionId, protocolVersion };

  const notifRes = await mcpPost(
    baseUrl,
    timeout,
    debug,
    { jsonrpc: '2.0', method: 'notifications/initialized', params: {} },
    sessionOpts,
    mcpDump ? { dir: mcpDump.dir, tag: `${mcpDump.queryTag}_initialized_notif` } : null
  );
  if (notifRes.statusCode !== 202 && notifRes.statusCode !== 200) {
    throw new Error(`MCP notifications/initialized HTTP ${notifRes.statusCode}`);
  }

  const callRes = await mcpPost(
    baseUrl,
    timeout,
    debug,
    {
      jsonrpc: '2.0',
      id:      1,
      method:  'tools/call',
      params: {
        name:      'query',
        arguments: {
          query:           queryText,
          repo,
          limit,
          max_symbols:     maxSymbols,
          include_content: includeContent,
        },
      },
    },
    sessionOpts,
    mcpDump ? { dir: mcpDump.dir, tag: `${mcpDump.queryTag}_tools_call_query` } : null
  );

  if (callRes.statusCode !== 200) {
    throw new Error(`MCP tools/call HTTP ${callRes.statusCode}: ${callRes.body.slice(0, 200)}`);
  }
  const callMessages = parseSseJsonMessages(callRes.body);
  const toolResult = findRpcResult(callMessages, 1);
  if (!toolResult || !toolResult.content || !toolResult.content[0]) {
    throw new Error('MCP tools/call: empty or unexpected result');
  }
  const block = toolResult.content[0];
  if (block.type !== 'text' || typeof block.text !== 'string') {
    throw new Error('MCP tools/call: expected text content');
  }
  return parseToolResultText(block.text);
}

// ─── REST mapping (gitnexus serve) ───────────────────────────────────────────

function repoJsonToContext(repoJson) {
  if (!repoJson || repoJson.error) return repoJson || {};
  const s = repoJson.stats || {};
  const languages = s.languages;
  return {
    projectName: repoJson.name,
    repoPath:    repoJson.repoPath,
    indexedAt:   repoJson.indexedAt,
    stats: {
      fileCount:      s.files,
      functionCount:  s.nodes,
      processCount:   s.processes,
      communities:    s.communities,
      edges:          s.edges,
      embeddings:     s.embeddings,
      languages,
    },
    languages,
  };
}

function normalizeCluster(c) {
  const name = c.name || c.heuristicLabel || c.label || String(c.id ?? '');
  const description = c.description || '';
  return Object.assign({}, c, { name, description });
}

function normalizeProcess(p) {
  const name = p.name || p.heuristicLabel || p.label || String(p.id ?? '');
  const description = p.description || `${p.processType || p.type || ''} steps:${p.stepCount ?? ''}`;
  return Object.assign({}, p, { name, description });
}

/** Same tolerances as detect-project-kind.js (UTF-8 BOM + UTF-16 LE). */
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

/**
 * When GET /api/clusters or /api/processes returns empty arrays but Cypher overview has data,
 * merge from gnx-tools `overview --out` JSON (same shape as cmdOverview output).
 */
function applyOverviewMergeIfNeeded({ clustersRaw, processesRaw, outPath, mergeOverview, noAutoOverview }) {
  const meta = {
    used: false,
    path: null,
    reasons: [],
    clusterCount: 0,
    processCount: 0,
  };
  const cr = Array.isArray(clustersRaw) ? clustersRaw : [];
  const pr = Array.isArray(processesRaw) ? processesRaw : [];
  const needsClusters = cr.length === 0;
  const needsProcesses = pr.length === 0;
  if (!needsClusters && !needsProcesses) {
    return { clustersRaw: cr, processesRaw: pr, meta };
  }

  let candidate = mergeOverview && String(mergeOverview).trim();
  if (candidate && !fs.existsSync(candidate)) {
    candidate = null;
  }
  if (!candidate && !noAutoOverview && outPath) {
    const auto = path.join(path.dirname(outPath), 'overview.json');
    if (fs.existsSync(auto)) candidate = auto;
  }
  if (!candidate) {
    return { clustersRaw: cr, processesRaw: pr, meta };
  }

  let ov;
  try {
    ov = readJsonFileRobust(candidate);
  } catch (e) {
    meta.parseError = String(e.message || e);
    return { clustersRaw: cr, processesRaw: pr, meta };
  }
  if (!ov || typeof ov !== 'object') {
    return { clustersRaw: cr, processesRaw: pr, meta };
  }

  let nextC = cr;
  let nextP = pr;
  if (needsClusters && Array.isArray(ov.clusters) && ov.clusters.length > 0) {
    nextC = ov.clusters;
    meta.reasons.push('rest-clusters-empty');
    meta.clusterCount = ov.clusters.length;
  }
  if (needsProcesses && Array.isArray(ov.processes) && ov.processes.length > 0) {
    nextP = ov.processes;
    meta.reasons.push('rest-processes-empty');
    meta.processCount = ov.processes.length;
  }

  if (nextC !== cr || nextP !== pr) {
    meta.used = true;
    meta.path = candidate;
  }
  return { clustersRaw: nextC, processesRaw: nextP, meta };
}

// ─── Safe fetch wrappers ──────────────────────────────────────────────────────

async function safeGet(url, timeout, debug, label, dumpDir) {
  try {
    const dumpBase = `rest-get_${String(label).replace(/[^a-zA-Z0-9_-]+/g, '_')}`;
    const result = dumpDir
      ? await restGetWithOptionalDump(url, timeout, debug, dumpDir, dumpBase)
      : await httpGet(url, timeout, debug);
    process.stderr.write(`  ✓ ${label}\n`);
    return result;
  } catch (err) {
    process.stderr.write(`  ✗ ${label}: ${err.message}\n`);
    return null;
  }
}

async function safeMcpQuery(baseUrl, timeout, debug, repo, queryText, label, queryOpts, dumpDir) {
  try {
    const mcpDump = dumpDir
      ? { dir: dumpDir, queryTag: String(label).replace(/[^a-zA-Z0-9_-]+/g, '_') }
      : null;
    const result = await mcpQueryTool(baseUrl, timeout, debug, repo, queryText, queryOpts || {}, mcpDump);
    if (mcpDump && result != null) {
      writeDebugJson(dumpDir, `mcp-parsed_${mcpDump.queryTag}.json`, result);
    }
    process.stderr.write(`  ✓ ${label}\n`);
    return result;
  } catch (err) {
    process.stderr.write(`  ✗ ${label}: ${err.message}\n`);
    if (dumpDir) {
      writeDebugFile(dumpDir, `mcp-error_${String(label).replace(/[^a-zA-Z0-9_-]+/g, '_')}.txt`, String(err.message || err));
    }
    return null;
  }
}

/** Collect source file paths from query JSON for agent follow-up reads (dedup, cap). */
function collectPathsFromQueryPayload(obj, max = 48) {
  const seen = new Set();
  const out = [];
  const pathKeys = new Set(['filePath', 'file_path', 'path']);

  function visit(node) {
    if (out.length >= max || node === null || node === undefined) return;
    if (typeof node === 'string') return;
    if (Array.isArray(node)) {
      for (const x of node) visit(x);
      return;
    }
    if (typeof node !== 'object') return;
    for (const [k, v] of Object.entries(node)) {
      if (pathKeys.has(k) && typeof v === 'string' && v.length > 1 && (v.includes('/') || v.includes('\\'))) {
        if (!seen.has(v)) {
          seen.add(v);
          out.push(v);
          if (out.length >= max) return;
        }
      } else {
        visit(v);
      }
    }
  }
  visit(obj);
  return out;
}

// ─── Architecture layer classification ───────────────────────────────────────

const LAYER_SIGNALS = {
  proxy:  ['gateway', 'proxy', 'load.?balancer', 'ingress', 'reverse.?proxy', 'nginx', 'traefik', 'envoy'],
  api:    ['handler', 'controller', 'route', 'router', 'middleware', 'endpoint', 'rest', 'graphql', 'grpc', 'websocket', 'http', 'server', 'request', 'response'],
  data:   ['repository', 'model', 'schema', 'migration', 'store', 'storage', 'cache', 'redis', 'database', 'db', 'sql', 'mongo', 'orm', 'entity', 'record'],
  infra:  ['config', 'logger', 'log', 'util', 'helper', 'build', 'deploy', 'docker', 'k8s', 'telemetry', 'metric', 'tracing', 'auth', 'security', 'crypto'],
};

function classifyToLayer(name, filePath) {
  const text = `${name} ${filePath || ''}`.toLowerCase();
  const scores = {};
  for (const [layer, signals] of Object.entries(LAYER_SIGNALS)) {
    scores[layer] = signals.filter(sig => new RegExp(sig).test(text)).length;
  }
  const best = Object.entries(scores).sort((a, b) => b[1] - a[1])[0];
  return best[1] > 0 ? best[0] : 'api';
}

function classifyClusters(clusters) {
  const layers = { proxy: [], api: [], data: [], infra: [] };
  if (!Array.isArray(clusters)) return layers;
  for (const cluster of clusters) {
    const layer = classifyToLayer(cluster.name || '', cluster.description || '');
    layers[layer].push(cluster);
  }
  return layers;
}

// ─── Source tree scanning (Phase 1b pre-scan, requires --scan-source) ─────────

/**
 * BUILD_FILES: files that describe the repo's build system and dependencies.
 * The agent MUST read these before drawing any architecture diagram.
 */
const BUILD_FILE_NAMES = new Set([
  'readme', 'readme.md', 'readme.txt', 'readme.rst',
  'makefile', 'makefile.incl', 'makefile.incl.common', 'make.sh', 'makeall', 'makeclean',
  'cmakelists.txt',
  'package.json', 'package-lock.json',
  'go.mod', 'go.sum',
  'pyproject.toml', 'setup.py', 'setup.cfg', 'requirements.txt',
  'cargo.toml',
  'pom.xml', 'build.gradle', 'build.gradle.kts',
]);

/**
 * ENTRY_POINT_PATTERNS: patterns that identify executable entry-point source files.
 * The agent MUST read these to understand process topology.
 */
const ENTRY_PATTERNS = [
  /\bmain\b.*\.(cpp|cc|c|go|py|ts|js|java|kt|rs)$/i,
  /^main\.(cpp|cc|c|go|py|ts|js|java|kt|rs)$/i,
  /^(index|app|server|daemon|service|worker|cmd)\.(ts|js|go|py)$/i,
  /^mdb[A-Za-z]+\.cpp$/i,
];

/**
 * HEADER_PRIORITY: for C/C++ directories, prefer files matching these patterns
 * as the representative interface file to read.
 */
const HEADER_PRIORITY_PATTERNS = [
  /Mgr\.h$/i,
  /Manager\.h$/i,
  /Main\.h$/i,
  /Service\.h$/i,
  /Common\.h$/i,
  /Base\.h$/i,
  /\.h$/,
];

function detectLanguage(files) {
  const counts = {};
  for (const f of files) {
    const ext = path.extname(f).toLowerCase();
    if (ext) counts[ext] = (counts[ext] || 0) + 1;
  }
  const sorted = Object.entries(counts).sort((a, b) => b[1] - a[1]);
  if (!sorted.length) return 'unknown';
  const top = sorted[0][0];
  const langMap = { '.cpp': 'C++', '.cc': 'C++', '.c': 'C', '.h': 'C/C++', '.go': 'Go',
    '.py': 'Python', '.ts': 'TypeScript', '.js': 'JavaScript', '.java': 'Java',
    '.kt': 'Kotlin', '.rs': 'Rust', '.rb': 'Ruby', '.cs': 'C#' };
  return langMap[top] || top;
}

function scanSourceTree(repoRoot, maxDirs = 20) {
  if (!repoRoot || !fs.existsSync(repoRoot)) return null;

  const result = {
    repoRoot,
    detectedLanguage: 'unknown',
    buildFiles: [],
    entryPoints: [],
    subDirectories: [],
    representativeHeaders: [],
    sourceFileSummary: {},
  };

  let allFiles = [];
  try {
    allFiles = walkDir(repoRoot, 4);
  } catch (e) {
    return result;
  }

  result.detectedLanguage = detectLanguage(allFiles);

  // Build files (relative paths)
  for (const f of allFiles) {
    const rel = path.relative(repoRoot, f);
    const base = path.basename(f).toLowerCase();
    if (BUILD_FILE_NAMES.has(base)) {
      result.buildFiles.push(rel);
    }
  }

  // Entry points
  for (const f of allFiles) {
    const rel = path.relative(repoRoot, f);
    const base = path.basename(f);
    if (ENTRY_PATTERNS.some(p => p.test(base))) {
      result.entryPoints.push(rel);
    }
  }

  // Subdirectory inventory
  let topDirs = [];
  try {
    topDirs = fs.readdirSync(repoRoot, { withFileTypes: true })
      .filter(d => d.isDirectory() && !d.name.startsWith('.') && d.name !== 'node_modules')
      .map(d => d.name);
  } catch (_) {}

  // Count files per dir
  const dirFileCounts = {};
  for (const f of allFiles) {
    const rel = path.relative(repoRoot, f);
    const parts = rel.split(path.sep);
    if (parts.length >= 2) {
      const topDir = parts[0];
      dirFileCounts[topDir] = (dirFileCounts[topDir] || 0) + 1;
    }
  }

  // Score directories for importance
  const IMPORTANT_DIR_KEYWORDS = ['core', 'main', 'common', 'base', 'manager', 'ctrl',
    'control', 'service', 'agent', 'interface', 'api', 'server', 'cmd'];

  const scoredDirs = topDirs.map(d => {
    const lower = d.toLowerCase();
    const importanceScore = IMPORTANT_DIR_KEYWORDS.filter(k => lower.includes(k)).length;
    const fileCount = dirFileCounts[d] || 0;
    return { name: d, fileCount, importanceScore };
  }).sort((a, b) => (b.importanceScore * 100 + b.fileCount) - (a.importanceScore * 100 + a.fileCount));

  result.subDirectories = scoredDirs.map(d => ({
    name: d.name,
    fileCount: d.fileCount,
    language: detectLanguage(allFiles.filter(f => {
      const rel = path.relative(repoRoot, f);
      return rel.startsWith(d.name + path.sep);
    })),
  }));

  // Representative headers/interfaces per top-level dir (C/C++ focus, generalizable)
  const selectedDirs = scoredDirs.slice(0, maxDirs);
  for (const dir of selectedDirs) {
    const dirPath = path.join(repoRoot, dir.name);
    let dirFiles = [];
    try {
      dirFiles = fs.readdirSync(dirPath, { withFileTypes: true })
        .filter(f => f.isFile())
        .map(f => f.name);
    } catch (_) { continue; }

    let best = null;
    for (const pat of HEADER_PRIORITY_PATTERNS) {
      const match = dirFiles.find(f => pat.test(f));
      if (match) { best = match; break; }
    }
    if (best) {
      result.representativeHeaders.push(path.join(dir.name, best));
    }
  }

  // File count summary per extension
  const extCounts = {};
  for (const f of allFiles) {
    const ext = path.extname(f).toLowerCase() || '(no ext)';
    extCounts[ext] = (extCounts[ext] || 0) + 1;
  }
  result.sourceFileSummary = extCounts;
  result.totalFiles = allFiles.length;

  return result;
}

/**
 * Walk a directory recursively up to maxDepth, returning absolute file paths.
 * Skips hidden dirs, node_modules, .git, build/dist/out directories.
 */
function walkDir(dir, maxDepth, currentDepth = 0) {
  if (currentDepth > maxDepth) return [];
  const SKIP_DIRS = new Set(['.git', 'node_modules', '.svn', 'dist', 'build', 'out',
    '__pycache__', 'vendor', 'target', '.cache', 'coverage']);
  const results = [];
  let entries;
  try { entries = fs.readdirSync(dir, { withFileTypes: true }); } catch (_) { return []; }
  for (const entry of entries) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name.startsWith('.') || SKIP_DIRS.has(entry.name.toLowerCase())) continue;
      results.push(...walkDir(full, maxDepth, currentDepth + 1));
    } else if (entry.isFile()) {
      results.push(full);
    }
  }
  return results;
}

// ─── Index quality assessment ──────────────────────────────────────────────────

function assessIndexQuality(context, layeredClusters) {
  const stats = (context && context.stats) || {};
  const embeddings = stats.embeddings || 0;
  const communities = stats.communities || 0;
  const fileCount = stats.fileCount || 0;

  const apiClusters = (layeredClusters && layeredClusters.api) ? layeredClusters.api.length : 0;
  const totalClusters = Object.values(layeredClusters || {}).reduce((s, arr) => s + (arr ? arr.length : 0), 0);
  const apiRatio = totalClusters > 0 ? apiClusters / totalClusters : 0;

  const issues = [];
  if (embeddings === 0) {
    issues.push('embeddings=0: semantic queries unreliable; layer classification based on keywords only');
  }
  if (apiRatio > 0.85 && totalClusters > 5) {
    issues.push(`cluster collapse: ${Math.round(apiRatio * 100)}% of clusters assigned to api layer (likely misclassified)`);
  }
  if (fileCount > 0 && communities > 0 && communities / fileCount < 0.03) {
    issues.push(`low cluster density: ${communities} clusters for ${fileCount} files — many modules ungrouped`);
  }

  return {
    embeddingsEnabled: embeddings > 0,
    embeddingsCount: embeddings,
    reliabilityLevel: embeddings > 0 ? 'semantic' : 'keyword-only',
    clusterCollapseDetected: apiRatio > 0.85 && totalClusters > 5,
    issues,
    recommendation: embeddings === 0
      ? 'Run `npx gitnexus analyze --embeddings` then re-export for accurate semantic clustering'
      : 'Index appears healthy for semantic queries',
  };
}

// ─── Process classification (daemon vs tool) ─────────────────────────────────

const DAEMON_SIGNALS  = ['server', 'daemon', 'service', 'worker', 'listener', 'start', 'run', 'main', 'boot', 'init'];
const TOOL_SIGNALS    = ['cli', 'command', 'cmd', 'tool', 'script', 'job', 'task', 'batch', 'migrate', 'seed', 'generate', 'build'];

function classifyProcess(proc) {
  const text = `${proc.name || ''} ${proc.description || ''}`.toLowerCase();
  const daemonScore = DAEMON_SIGNALS.filter(s => text.includes(s)).length;
  const toolScore   = TOOL_SIGNALS.filter(s => text.includes(s)).length;
  return daemonScore >= toolScore ? 'daemon' : 'tool';
}

// ─── Tech stack extraction ─────────────────────────────────────────────────────

function extractTechStack(context) {
  const stack = {
    languages:      [],
    frameworks:     [],
    runtime:        null,
    packageManager: null,
  };

  if (!context) return stack;

  const langs = context.languages || (context.stats && context.stats.languages);
  if (langs && typeof langs === 'object' && !Array.isArray(langs)) {
    stack.languages = Object.entries(langs)
      .sort((a, b) => (b[1] || 0) - (a[1] || 0))
      .map(([lang, pct]) => ({ lang, pct: typeof pct === 'number' ? `${pct}%` : String(pct) }));
  }

  if (context.runtime) stack.runtime = context.runtime;
  if (context.packageManager) stack.packageManager = context.packageManager;

  return stack;
}

// ─── Main ─────────────────────────────────────────────────────────────────────

async function main() {
  const args = parseArgs(process.argv.slice(2));

  if (!args.url) {
    console.error('Error: --url <GITNEXUS_URL> is required');
    console.error('Usage: node fetch-arch-data.js --url http://127.0.0.1:11011 --repo MyRepo_user');
    process.exit(1);
  }

  const baseUrl = args.url.replace(/\/$/, '');
  const encRepo = encodeURIComponent;

  const dumpDir = ensureDebugDumpDir(args.debugDump);
  if (dumpDir) {
    writeDebugFile(dumpDir, 'README.txt',
      'fetch-arch-data --debug-dump output\n'
      + '- rest-get_*.http.txt : raw HTTP body (UTF-8)\n'
      + '- rest-get_*.json     : parsed JSON when parse succeeded\n'
      + '- mcp_*_*.sse.txt     : raw MCP Streamable HTTP bodies\n'
      + '- mcp-parsed_*.json   : parsed tool result object after tools/call\n'
      + `generated: ${new Date().toISOString()}\n`);
  }

  if (args.list) {
    process.stderr.write(`Fetching repo list from ${baseUrl}...\n`);
    const repos = await safeGet(`${baseUrl}/api/repos`, args.timeout, args.debug, 'List repos (GET /api/repos)', dumpDir);
    console.log(JSON.stringify(repos, null, 2));
    return;
  }

  if (!args.repo) {
    console.error('Error: --repo <REPO_NAME> is required (or use --list to see available repos)');
    process.exit(1);
  }

  const repo = args.repo;
  const outPath = path.isAbsolute(args.out) ? args.out : path.join(process.cwd(), args.out);

  process.stderr.write(`\nCollecting architecture data for repo "${repo}" from ${baseUrl}\n`);
  process.stderr.write('─'.repeat(60) + '\n');

  process.stderr.write('\n[1/4] Core resources (REST /api/*)\n');

  const repoJson  = await safeGet(`${baseUrl}/api/repo?repo=${encRepo(repo)}`, args.timeout, args.debug, 'repo meta', dumpDir);
  const clustersJ = await safeGet(`${baseUrl}/api/clusters?repo=${encRepo(repo)}`, args.timeout, args.debug, 'clusters', dumpDir);
  const processesJ = await safeGet(`${baseUrl}/api/processes?repo=${encRepo(repo)}`, args.timeout, args.debug, 'processes', dumpDir);

  const context = repoJsonToContext(repoJson);

  const snippetOpts = args.withSnippets
    ? { include_content: true, limit: 6, max_symbols: 5 }
    : { include_content: false, limit: 8, max_symbols: 8 };

  process.stderr.write('\n[2/4] Targeted concept queries (MCP tools/call query)\n');
  if (args.withSnippets) {
    process.stderr.write('  (include_content enabled — smaller limits to control payload)\n');
  }

  const [qDaemon, qTool, qData, qApi, qInfra, qProduct] = await Promise.all([
    safeMcpQuery(baseUrl, args.timeout, args.debug, repo,
      'entry point main daemon server startup boot', 'query: daemon/server', snippetOpts, dumpDir),
    safeMcpQuery(baseUrl, args.timeout, args.debug, repo,
      'cli tool command batch job migrate script', 'query: cli/tool', snippetOpts, dumpDir),
    safeMcpQuery(baseUrl, args.timeout, args.debug, repo,
      'database storage persistence cache repository', 'query: data layer', snippetOpts, dumpDir),
    safeMcpQuery(baseUrl, args.timeout, args.debug, repo,
      'api route handler middleware http endpoint', 'query: api layer', snippetOpts, dumpDir),
    safeMcpQuery(baseUrl, args.timeout, args.debug, repo,
      'configuration infrastructure deployment logger util', 'query: infra layer', snippetOpts, dumpDir),
    safeMcpQuery(baseUrl, args.timeout, args.debug, repo,
      'core domain business logic feature workflow user-facing', 'query: domain/business', snippetOpts, dumpDir),
  ]);

  process.stderr.write('\n[3/5] Classifying architecture\n');

  let clustersRaw = (clustersJ && (clustersJ.clusters || clustersJ)) || [];
  let processesRaw = (processesJ && (processesJ.processes || processesJ)) || [];
  const overviewMerged = applyOverviewMergeIfNeeded({
    clustersRaw,
    processesRaw,
    outPath,
    mergeOverview: args.mergeOverview,
    noAutoOverview: args.noAutoOverview,
  });
  clustersRaw = overviewMerged.clustersRaw;
  processesRaw = overviewMerged.processesRaw;
  if (overviewMerged.meta.used) {
    process.stderr.write(`  ℹ Merged from overview JSON: ${overviewMerged.meta.clusterCount} clusters, ${overviewMerged.meta.processCount} processes\n`);
    process.stderr.write(`     file: ${overviewMerged.meta.path}\n`);
    process.stderr.write(`     reasons: ${overviewMerged.meta.reasons.join(', ')}\n`);
  } else if (overviewMerged.meta.parseError) {
    process.stderr.write(`  ⚠ overview merge skipped (parse error): ${overviewMerged.meta.parseError}\n`);
  }

  const clustersArr = Array.isArray(clustersRaw) ? clustersRaw.map(normalizeCluster) : [];
  const processesArr = Array.isArray(processesRaw) ? processesRaw.map(normalizeProcess) : [];

  const layeredClusters = classifyClusters(clustersArr);
  const techStack       = extractTechStack(context);

  const processInventory = { daemon: [], tool: [] };
  for (const proc of processesArr) {
    const type = classifyProcess(proc);
    processInventory[type].push(proc);
  }

  const addQueryProcesses = (queryResult, type) => {
    if (!queryResult) return;
    const procs = queryResult.processes || queryResult.results || [];
    if (!Array.isArray(procs)) return;
    for (const p of procs) {
      const np = normalizeProcess(p);
      const key = type || classifyProcess(np);
      if (!processInventory[key].find(x => x.name === np.name)) {
        processInventory[key].push(np);
      }
    }
  };
  addQueryProcesses(qDaemon, 'daemon');
  addQueryProcesses(qTool,   'tool');
  addQueryProcesses(qProduct, null);

  process.stderr.write('\n[4/5] Assessing index quality\n');
  const indexQuality = assessIndexQuality(context, layeredClusters);
  for (const issue of indexQuality.issues) {
    process.stderr.write(`  ⚠ ${issue}\n`);
  }
  if (!indexQuality.issues.length) {
    process.stderr.write(`  ✓ ${indexQuality.recommendation}\n`);
  }

  process.stderr.write('\n[5/5] Building output\n');

  // Source tree scan (if --scan-source provided)
  let sourceScan = null;
  if (args.scanSource) {
    process.stderr.write(`  Scanning source tree: ${args.scanSource}\n`);
    sourceScan = scanSourceTree(args.scanSource);
    if (sourceScan) {
      process.stderr.write(`  ✓ Source scan: ${sourceScan.totalFiles} files, ${sourceScan.subDirectories.length} top-level dirs\n`);
      process.stderr.write(`  ✓ Entry points found: ${sourceScan.entryPoints.length}\n`);
      process.stderr.write(`  ✓ Build files found: ${sourceScan.buildFiles.length}\n`);
      process.stderr.write(`  ✓ Representative headers: ${sourceScan.representativeHeaders.length}\n`);
    }
  } else {
    process.stderr.write('  ℹ  No --scan-source provided. Add --scan-source <workspace-root> for Phase 1b pre-scan.\n');
  }

  const suggestedSourceFiles = (() => {
    const acc = new Set();
    for (const q of [qDaemon, qTool, qData, qApi, qInfra, qProduct]) {
      for (const p of collectPathsFromQueryPayload(q, 64)) acc.add(p);
    }
    // Also include representative headers from source scan
    if (sourceScan) {
      for (const h of sourceScan.representativeHeaders) acc.add(h);
      for (const e of sourceScan.entryPoints.slice(0, 20)) acc.add(e);
    }
    return [...acc].slice(0, 80);
  })();

  const output = {
    meta: {
      repo,
      serverUrl:     baseUrl,
      generatedAt:   new Date().toISOString(),
      skillVersion:  '1.5.0',
      withSnippets:  args.withSnippets,
      scanSource:    args.scanSource || null,
      debugDumpDir:  dumpDir || null,
      overviewMerge: overviewMerged.meta.used ? overviewMerged.meta : { used: false },
    },
    context: context || {},
    techStack,
    /**
     * indexQuality: agent MUST check this before using layeredClusters.
     * If reliabilityLevel === 'keyword-only', do NOT use cluster layer assignments
     * in the architecture document — derive layers from source tree instead.
     */
    indexQuality,
    layeredClusters,
    processInventory,
    rawClusters:  clustersArr,
    rawProcesses: processesArr,
    queryResults: {
      daemon:  qDaemon,
      tool:    qTool,
      data:    qData,
      api:     qApi,
      infra:   qInfra,
      product: qProduct,
    },
    /**
     * suggestedSourceFiles: paths for the agent to Read in Phase 1b.
     * Priority order: representativeHeaders (per-directory) > entryPoints > query hits.
     * These are repo-relative paths — prepend the workspace root to open files.
     */
    suggestedSourceFiles,
    /**
     * sourceScan: pre-scan of the local workspace (only present with --scan-source).
     * - buildFiles: MUST be read before drawing diagrams
     * - entryPoints: MUST be read to understand process topology
     * - representativeHeaders: read 1 per directory to understand module interfaces
     * - subDirectories: all top-level dirs with file counts and detected language
     */
    sourceScan,
    diagrams: {
      systemOverview: {
        description: 'Layered architecture: Proxy → API → Data → Infrastructure',
        note: indexQuality.clusterCollapseDetected
          ? 'WARNING: cluster layer assignments unreliable — derive layers from sourceScan.subDirectories instead'
          : 'Cluster assignments have reasonable distribution',
        layers: ['proxy', 'api', 'data', 'infra'],
        layerContents: layeredClusters,
      },
      executionFlows: {
        description: 'Top daemon and tool execution flows',
        daemons: processInventory.daemon.slice(0, 5),
        tools:   processInventory.tool.slice(0, 5),
      },
      techStack: {
        description: 'Technology stack dependency tree',
        stack: techStack,
        note: 'Verify and enrich from sourceScan.buildFiles (read Makefile/CMakeLists/go.mod etc.)',
      },
    },
  };

  fs.writeFileSync(outPath, JSON.stringify(output, null, 2), 'utf-8');

  // ─── 自动生成 arch-data-summary.txt ──────────────────────────────────────────
  // 预提取常用字段，避免后续每次都要解析 3000+ 行大 JSON
  // processInventory 结构为 { daemon: [...], tool: [...] }，不是直接数组
  const summaryLines = [
    '# arch-data-summary.txt — 自动生成，勿手动编辑',
    `# 来源: ${outPath}`,
    `# 生成时间: ${new Date().toISOString()}`,
    '',
    '## 索引质量',
    `embeddings          = ${context.stats.embeddings}`,
    `reliabilityLevel    = ${indexQuality.reliabilityLevel}`,
    `clusterCollapse     = ${indexQuality.clusterCollapseDetected}`,
    `issues              = ${indexQuality.issues.join('; ') || '无'}`,
    '',
    '## 仓库基本信息',
    `repoPath            = ${context.repoPath || '(unknown)'}`,
    `indexedAt           = ${context.indexedAt || '(unknown)'}`,
    `totalSymbols        = ${context.stats.symbols || 0}`,
    `totalCommunities    = ${context.stats.communities || 0}`,
    '',
    '## 聚类分布',
    `clusters.total      = ${clustersArr.length}`,
    `clusters.proxy      = ${layeredClusters.proxy.length}`,
    `clusters.api        = ${layeredClusters.api.length}`,
    `clusters.data       = ${layeredClusters.data.length}`,
    `clusters.infra      = ${layeredClusters.infra.length}`,
    '',
    '## 进程清单（processInventory 结构：{ daemon: [], tool: [] }）',
    `processes.daemon    = ${processInventory.daemon.length}`,
    `processes.tool      = ${processInventory.tool.length}`,
    '',
    '## 技术栈（语言）',
    ...techStack.languages.slice(0, 8).map(l => `  ${l.lang.padEnd(20)} ratio=${l.ratio}`),
    '',
    '## suggestedSourceFiles（前10条）',
    ...suggestedSourceFiles.slice(0, 10).map(f => `  ${f}`),
    suggestedSourceFiles.length > 10 ? `  ... 共 ${suggestedSourceFiles.length} 条` : '',
    '',
    '## 使用提示',
    '- embeddings=0 时索引分层不可信，架构分层须依赖源码目录结构',
    '- processInventory 访问方式: d.processInventory.daemon / d.processInventory.tool',
    '- 不要用 PowerShell node -e 解析 arch-data.json，请写独立 .js 文件',
  ].filter(l => l !== undefined).join('\n');

  const summaryPath = outPath.replace(/\.json$/, '-summary.txt');
  fs.writeFileSync(summaryPath, summaryLines + '\n', 'utf-8');

  process.stderr.write('\n' + '─'.repeat(60) + '\n');
  process.stderr.write(`✓ arch-data.json written to: ${outPath}\n`);
  process.stderr.write(`✓ arch-data-summary.txt written to: ${summaryPath}\n`);
  process.stderr.write(`  Clusters:  ${clustersArr.length} (proxy:${layeredClusters.proxy.length} api:${layeredClusters.api.length} data:${layeredClusters.data.length} infra:${layeredClusters.infra.length})\n`);
  process.stderr.write(`  Processes: ${processesArr.length} (daemon:${processInventory.daemon.length} tool:${processInventory.tool.length})\n`);
  process.stderr.write(`  Languages: ${techStack.languages.map(l => l.lang).join(', ') || 'unknown'}\n`);
  process.stderr.write(`  Index reliability: ${indexQuality.reliabilityLevel}\n`);
  if (sourceScan) {
    process.stderr.write(`  Source scan: ${sourceScan.totalFiles} files across ${sourceScan.subDirectories.length} dirs\n`);
  }
  if (indexQuality.issues.length) {
    process.stderr.write('\n⚠ Index quality issues detected — agent should rely on source scan for layer derivation.\n');
  }
  process.stderr.write('\nReady for document generation.\n');
}

main().catch(err => {
  console.error(`\nFatal: ${err.message}`);
  if (process.env.GITNEXUS_DEBUG || process.argv.includes('--debug')) {
    console.error(err.stack);
  }
  process.exit(1);
});
