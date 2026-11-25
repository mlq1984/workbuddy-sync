import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';

function selectedFile(workspace, value, output = false) {
  const name = path.resolve(workspace, value);
  const parent = fs.realpathSync(path.dirname(name));
  const relative = path.relative(workspace, path.join(parent, path.basename(name)));
  if (!relative || relative === '..' || relative.startsWith('..' + path.sep) || path.isAbsolute(relative)) {
    throw new Error('请选择当前项目内的文件。');
  }
  const found = path.join(parent, path.basename(name));
  if (fs.existsSync(found) && !fs.lstatSync(found).isFile()) throw new Error('请选择普通文本文件。');
  if (!output && !fs.existsSync(found)) throw new Error('所选原稿或修订正文尚未找到。');
  return found;
}

function readText(file) {
  const bytes = fs.readFileSync(file);
  const text = bytes.toString('utf8');
  if (!Buffer.from(text).equals(bytes) || text.includes('\0')) {
    throw new Error('请使用 UTF-8 编码的 Markdown 原稿和修订正文。');
  }
  return text;
}

function headings(text) {
  const found = [];
  let fence = null;
  for (const match of text.matchAll(/[^\r\n]*(?:\r\n|\n|\r|$)/g)) {
    if (!match[0]) continue;
    const line = match[0].replace(/[\r\n]+$/, '').replace(/^\uFEFF/, '');
    const marker = /^ {0,3}(`{3,}|~{3,})(.*)$/.exec(line);
    if (marker) {
      const run = marker[1];
      if (!fence && !(run[0] === '`' && marker[2].includes('`'))) fence = run;
      else if (fence && run[0] === fence[0] && run.length >= fence.length && !marker[2].trim()) fence = null;
      continue;
    }
    if (fence) continue;
    const heading = /^ {0,3}(#{1,6})[ \t]+(.+?)\s*$/.exec(line);
    if (heading) {
      found.push({ title: heading[2].replace(/[ \t]+#+\s*$/, '').trim(), level: heading[1].length,
        start: match.index, body: match.index + match[0].length });
    }
  }
  return { found, openFence: Boolean(fence) };
}

function sectionBounds(source, title) {
  const slots = headings(source).found;
  const matches = slots.filter(item => item.title === title);
  if (matches.length !== 1) throw new Error('没有找到唯一的章节标题。请核对标题，原稿已保留。');
  const current = matches[0];
  const next = slots.find(item => item.start > current.start && item.level <= current.level);
  const end = next ? next.start : source.length;
  return { current, next, end };
}

function replaceBody(source, title, replacement) {
  const { current, next, end } = sectionBounds(source, title);
  const old = source.slice(current.body, end);
  const check = headings(replacement);
  if (check.openFence || check.found.some(item => item.level <= current.level)) {
    throw new Error('修订正文包含同级或上级标题，或代码围栏未闭合。请只提供选定节的正文。');
  }
  const eol = (source.slice(current.start, current.body).match(/\r\n|\n|\r/) ||
    source.match(/\r\n|\n|\r/) || ['\n'])[0];
  const leading = old.match(/^(?:[ \t]*(?:\r\n|\n|\r))*/)[0];
  const trailing = old.slice(leading.length).match(/(?:(?:\r\n|\n|\r)[ \t]*)*$/)[0];
  const body = replacement.replace(/^\uFEFF/, '').replace(/^(?:[ \t]*[\r\n])+|(?:[\r\n][ \t]*)+$/g, '')
    .replace(/\r\n|\r|\n/g, eol);
  if (!body.trim()) throw new Error('请提供这一节的新正文。');
  const head = source.slice(0, current.body);
  const separator = /[\r\n]$/.test(head) ? '' : eol;
  return head + separator + leading + body + (trailing || (next ? eol : '')) + source.slice(end);
}

function publish(file, text) {
  const temporary = path.join(path.dirname(file), '.bookwriter-' + crypto.randomUUID() + '.tmp');
  const descriptor = fs.openSync(temporary, 'wx', 0o600);
  try {
    try { fs.writeFileSync(descriptor, text); fs.fsyncSync(descriptor); }
    finally { fs.closeSync(descriptor); }
    try { fs.linkSync(temporary, file); }
    catch (error) {
      if (error.code !== 'EEXIST') throw error;
      if (!fs.lstatSync(file).isFile() || readText(file) !== text) {
        throw new Error('同名文件已有不同内容。请另选新文件名，已有稿件已保留。');
      }
    }
  } finally { fs.rmSync(temporary, { force: true }); }
  if (readText(file) !== text) throw new Error('另存后的正文与预期不一致，请复核文件。');
}

export function reviseSection(workspace, options) {
  for (const name of ['source', 'heading', 'replacement', 'output']) {
    if (!options[name]) throw new Error('定段另存需要原稿、唯一章节标题、新正文文件和输出文件名。');
  }
  const source = selectedFile(workspace, options.source);
  const replacement = selectedFile(workspace, options.replacement);
  const output = selectedFile(workspace, options.output, true);
  if (new Set([source, replacement, output]).size !== 3) throw new Error('请给新版另选文件名，保留原稿和修订正文。');
  const before = readText(source);
  const revised = replaceBody(before, options.heading, readText(replacement));
  if (readText(source) !== before) throw new Error('原稿已经变化。请重新核对当前章节后再另存。');
  publish(output, revised);
  return { file: path.relative(workspace, output), heading: options.heading, originalPreserved: true };
}

export function reviewSection(workspace, options) {
  if (!options.source || !options.heading || !options.output) {
    throw new Error('请提供原稿、章节标题和新版文件名。');
  }
  const source = selectedFile(workspace, options.source);
  const output = selectedFile(workspace, options.output, true);
  const item = options['check-item'];
  const sentence = options['add-sentence'];
  const chosen = options.replacement ? selectedFile(workspace, options.replacement) : null;
  if ([item, sentence, chosen].filter(Boolean).length > 1) throw new Error('本次请选择补入一句、核对对象或替换正文中的一项。');
  if (sentence && (!sentence.trim() || /[\r\n\u0000]/.test(sentence))) throw new Error('请提供本题要补入的一句完整正文。');
  const prior = options['continue-from'] ? selectedFile(workspace, options['continue-from']) : source;
  if (output === source || output === prior) throw new Error('请给新版另选文件名，保留原稿及上一版。');
  if (chosen && [source, prior, output].includes(chosen)) throw new Error('修订正文请使用单独的文件。');
  if (options['continue-from'] && !item && !sentence && !chosen) throw new Error('请填写要在上一版补入的核对对象。');
  if (item && !/^[\p{L}\p{N}][\p{L}\p{N} \-]{0,35}$/u.test(item)) {
    throw new Error('请只填写本次要核对的对象，完整补句可使用 --add-sentence。');
  }
  const original = readText(source);
  const before = prior === source ? original : readText(prior);
  const { current, end } = sectionBounds(before, options.heading);
  const oldBody = before.slice(current.body, end);
  if (!oldBody.trim()) throw new Error('这节还没有原文。请先给出实际材料。');
  const chosenText = chosen ? readText(chosen) : null;
  let revised = before;
  if (chosenText !== null) {
    revised = replaceBody(before, options.heading, chosenText);
  } else if (item || sentence) {
    const addition = sentence ? sentence.trim() : '待核：' + item + '。';
    const lines = oldBody.split(/\r\n|\n|\r/);
    if (lines.some(line => line.trim() === addition)) {
      revised = before;
    } else {
      const newline = (before.slice(current.start, current.body).match(/\r\n|\n|\r/) || ['\n'])[0];
      const ending = oldBody.match(/(?:(?:\r\n|\n|\r)[ \t]*)*$/)[0];
      const insertAt = end - ending.length;
      revised = before.slice(0, insertAt) + newline + newline + addition + before.slice(insertAt);
    }
  }
  const updated = sectionBounds(revised, options.heading);
  const sectionText = revised.slice(updated.current.body, updated.end).trim();
  if (readText(source) !== original || (prior !== source && readText(prior) !== before) || (chosen && readText(chosen) !== chosenText)) {
    throw new Error('原稿或上一版已变化，请重新核对选定的文件。');
  }
  publish(output, revised);
  return { file: path.relative(workspace, output), original: path.relative(workspace, source),
    basedOn: path.relative(workspace, prior), heading: options.heading, sectionText, originalPreserved: true };
}
