#!/usr/bin/env node
// WorkBuddy two-level distribution entry. Every runtime source is a visible,
// individually hashed file in assets/. No remote code or nested archive is used.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

const VERSION = '2026.10.311';
const marketRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const digest = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
function inside(base, target) {
  const rel = path.relative(base, target);
  return rel === '' || (!path.isAbsolute(rel) && rel !== '..' && !rel.startsWith('..' + path.sep));
}
function safeRelative(value) {
  return typeof value === 'string' && value.length > 0 && value.length < 512 &&
    !/[\\\x00-\x1f:]/.test(value) && !path.posix.isAbsolute(value) &&
    value.split('/').every(part => part !== '' && part !== '.' && part !== '..');
}
function option(args, name) {
  let result;
  for (let i = 0; i < args.length; i++) if (args[i] === name) {
    if (!args[i + 1] || args[i + 1].startsWith('--')) throw new Error(name + ' 缺少路径');
    result = args[++i];
  }
  return result;
}
function loadManifest() {
  const manifestPath = path.join(marketRoot, 'assets', 'runtime-manifest.json');
  if (fs.statSync(manifestPath).size > 1024 * 1024) throw new Error('运行清单超过本地读取上限');
  const raw = fs.readFileSync(manifestPath);
  const m = JSON.parse(raw);
  if (m.schema !== 'fbs.bookwriter.flat-runtime/v2' || m.productId !== 'fbs-bookwriter' || m.version !== VERSION ||
      !Array.isArray(m.files) || !m.files.length || m.files.length > 2000) throw new Error('运行清单类型或版本不匹配');
  const destinations = new Set(), sources = new Set();
  let total = 0;
  const files = m.files.map(row => {
    if (!safeRelative(row.path) || !safeRelative(row.asset) || row.asset.split('/').length > 2 ||
        row.path === '.wb-runtime-ready.json' || (row.publicPath && !safeRelative(row.publicPath)) ||
        !/^[a-f0-9]{64}$/.test(row.sha256 || '') || !/^[a-f0-9]{64}$/.test(row.assetSha256 || '') ||
        !Number.isSafeInteger(row.bytes) || row.bytes < 0 || row.bytes > 3145728) throw new Error('运行清单包含非法路径/指纹');
    for (const [set, key] of [[destinations, row.path], [sources, row.asset]]) {
      const folded = key.toLowerCase();
      if (set.has(folded)) throw new Error('运行清单包含重复路径');
      set.add(folded);
    }
    const physical = path.join(marketRoot, row.asset);
    if (fs.lstatSync(physical).isSymbolicLink() || !inside(fs.realpathSync(marketRoot), fs.realpathSync(physical))) throw new Error('源资源越界');
    let bytes = fs.readFileSync(physical);
    if (bytes.length !== row.assetBytes || digest(bytes) !== row.assetSha256) throw new Error('随包资源指纹不匹配：' + row.path);
    if (row.restoreEdits !== undefined) {
      if (!Array.isArray(row.restoreEdits) || row.restoreEdits.length > 4096) throw new Error('非法运行文档恢复记录');
      let end = 0;
      for (const edit of row.restoreEdits) {
        if (!Array.isArray(edit) || edit.length !== 3 || !Number.isSafeInteger(edit[0]) || !Number.isSafeInteger(edit[1]) ||
            edit[0] < end || edit[1] < 0 || edit[0] + edit[1] > bytes.length || typeof edit[2] !== 'string' ||
            Buffer.byteLength(edit[2]) > 1024 * 1024) throw new Error('非法运行文档恢复范围');
        end = edit[0] + edit[1];
      }
      for (const [start, count, text] of [...row.restoreEdits].reverse()) {
        bytes = Buffer.concat([bytes.subarray(0, start), Buffer.from(text), bytes.subarray(start + count)]);
      }
    }
    total += bytes.length;
    if (total > 3145728 || bytes.length !== row.bytes || digest(bytes) !== row.sha256) throw new Error('运行文件指纹或大小不匹配：' + row.path);
    return { ...row, bytes };
  });
  return { ...m, files, manifestSha256: digest(raw) };
}
function workspaceFrom(args) {
  const requested = option(args, '--workspace') || option(args, '--book-root');
  if (!requested) throw new Error('请显式提供已选项目路径：--workspace <目录> 或 --book-root <目录>');
  const workspace = fs.realpathSync(path.resolve(requested));
  if (!fs.statSync(workspace).isDirectory()) throw new Error('项目路径不是目录');
  const bookRoot = option(args, '--book-root');
  if (bookRoot && fs.realpathSync(path.resolve(bookRoot)) !== workspace) throw new Error('workspace 与 book-root 必须指向同一已选项目');
  return workspace;
}
function validateRuntime(target, manifest) {
  const stamp = path.join(target, '.wb-runtime-ready.json');
  if (!fs.existsSync(stamp)) throw new Error('运行副本尚未准备完成；保留现场，请等待当前准备任务完成或换用新的项目目录');
  const record = JSON.parse(fs.readFileSync(stamp));
  if (record.manifestSha256 !== manifest.manifestSha256) throw new Error('已有运行副本版本不匹配；不覆盖');
  const real = fs.realpathSync(target);
  for (const row of manifest.files) {
    const p = path.join(target, row.path);
    if (!fs.existsSync(p) || fs.lstatSync(p).isSymbolicLink() || !inside(real, fs.realpathSync(p)) || digest(fs.readFileSync(p)) !== row.sha256) {
      throw new Error('已有运行源码被修改或缺失，不覆盖手改：' + row.path);
    }
  }
}
function prepare(workspace, manifest) {
  const base = path.join(workspace, '.bookwriter-runtime');
  if (!fs.existsSync(base)) fs.mkdirSync(base);
  if (fs.lstatSync(base).isSymbolicLink() || !inside(workspace, fs.realpathSync(base))) throw new Error('运行副本目录越出所选项目');
  const target = path.join(base, 'fbs-bookwriter-' + VERSION + '-' + manifest.manifestSha256.slice(0, 12));
  if (fs.existsSync(target)) {
    if (fs.lstatSync(target).isSymbolicLink() || !inside(workspace, fs.realpathSync(target))) throw new Error('已有运行副本越界');
    validateRuntime(target, manifest);
    return target;
  }
  fs.mkdirSync(target);
  for (const row of manifest.files) {
    const dest = path.join(target, row.path);
    if (!inside(target, dest)) throw new Error('目标路径越界');
    fs.mkdirSync(path.dirname(dest), { recursive: true });
    fs.writeFileSync(dest, row.bytes, { flag: 'wx' });
  }
  fs.writeFileSync(path.join(target, '.wb-runtime-ready.json'), JSON.stringify({ productId: manifest.productId, version: VERSION, manifestSha256: manifest.manifestSha256 }) + '\n', { flag: 'wx' });
  validateRuntime(target, manifest);
  return target;
}
function npmCli() {
  const dirs = [path.dirname(process.execPath), ...(process.env.PATH || '').split(path.delimiter)];
  const candidates = [process.env.npm_execpath, ...dirs.map(p => path.join(p, 'node_modules', 'npm', 'bin', 'npm-cli.js'))];
  const found = candidates.find(p => p && path.basename(p) === 'npm-cli.js' && fs.existsSync(p));
  if (!found) throw new Error('未找到本机npm；请在运行副本目录使用已安装的npm执行 npm ci --ignore-scripts');
  return found;
}
function execute(program, args, cwd) {
  const r = spawnSync(program, args, { cwd, stdio: 'inherit', shell: false, windowsHide: true, timeout: 300_000 });
  if (r.error) throw new Error(r.error.code === 'ETIMEDOUT' ? '本地命令超时并已终止' : r.error.message);
  return r.status ?? 1;
}
function main() {
  const args = process.argv.slice(2);
  if (!args.length || args[0] === '--help') {
    console.log('BookWriter ' + VERSION + '\nlocate <源码逻辑路径>\nprepare --workspace <项目>\ninstall --workspace <项目>\nrun scripts/<入口>.mjs --book-root <项目> [原脚本参数]\n--version');
    return 0;
  }
  if (args[0] === '--version') { console.log(VERSION); return 0; }
  if (args[0] === 'locate') {
    const m = loadManifest(), row = m.files.find(item => item.path === args[1]);
    if (!row) throw new Error('逻辑路径不在随包资源清单内');
    const file = path.join(marketRoot, row.publicPath || row.asset);
    if (fs.lstatSync(file).isSymbolicLink() || !inside(fs.realpathSync(marketRoot), fs.realpathSync(file))) throw new Error('资料路径越界');
    console.log(JSON.stringify({ logicalPath: row.path, file, sha256: digest(fs.readFileSync(file)), runtimeSourceSha256: row.sha256 }));
    return 0;
  }
  if (!['prepare', 'install', 'run'].includes(args[0])) throw new Error('未知命令');
  const manifest = loadManifest(), workspace = workspaceFrom(args);
  if (args[0] === 'run' && (!safeRelative(args[1]) || !args[1].endsWith('.mjs') || !manifest.files.some(row => row.path === args[1]))) throw new Error('入口不在随包源码清单中');
  const target = prepare(workspace, manifest);
  if (args[0] === 'prepare') {
    console.log(JSON.stringify({ productId: manifest.productId, version: VERSION, runtimeRoot: target, files: manifest.files.length, manifestSha256: manifest.manifestSha256 }));
    return 0;
  }
  if (args[0] === 'install') return execute(process.execPath, [npmCli(), 'ci', '--ignore-scripts', '--no-audit', '--no-fund', '--registry=https://registry.npmjs.org'], target);
  const forwarded = [];
  for (let i = 2; i < args.length; i++) {
    if (args[i] === '--workspace' || args[i] === '--skill-root') { i++; continue; }
    if (args[i] === '--book-root') { forwarded.push('--book-root', workspace); i++; continue; }
    forwarded.push(args[i]);
  }
  return execute(process.execPath, [path.join(target, args[1]), ...forwarded, '--skill-root', target], workspace);
}
try { process.exitCode = main(); } catch (error) { console.error('BookWriter：' + error.message); process.exitCode = 1; }
