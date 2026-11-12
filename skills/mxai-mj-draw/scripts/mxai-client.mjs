#!/usr/bin/env node
import { open, readFile } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

import { ClientError, createAuthorization } from './authorization.mjs';
export { ClientError } from './authorization.mjs';
const REQUEST_TIMEOUT_MS = 30_000;
const MAX_IMAGE_BYTES = 20 * 1024 * 1024;
const POLL_INTERVAL_MS = 4000;

export function redact(value, secrets = []) {
  if (typeof value === 'string') {
    let text = value
      .replace(/\b(?:sks_|nb_)[a-f0-9]{32,}\b/gi, '[已隐藏]')
      .replace(/Bearer\s+[^\s"']+/gi, 'Bearer [已隐藏]');
    for (const secret of secrets) if (secret) text = text.split(secret).join('[已隐藏]');
    return text;
  }
  if (Array.isArray(value)) return value.map(item => redact(item, secrets));
  if (value && typeof value === 'object')
    return Object.fromEntries(
      Object.entries(value).map(([key, item]) => [
        key,
        /token|credential|skill_key|api_key|authorization(?!_url)/i.test(key)
          ? '[已隐藏]'
          : redact(item, secrets),
      ]),
    );
  return value;
}

function baseURL(value) {
  const url = new URL(value);
  if (
    url.username ||
    url.password ||
    url.search ||
    url.hash ||
    (url.protocol !== 'https:' &&
      !(url.protocol === 'http:' && ['localhost', '127.0.0.1'].includes(url.hostname)))
  )
    throw new ClientError(
      'invalid_configuration',
      '服务地址必须使用 HTTPS，本地测试仅允许回环地址',
    );
  return url.href.replace(/\/+$/, '');
}

/** 不根据扩展名判断上传格式，防止伪装图片进入生成链路。 */
export async function imageData(file) {
  const handle = await open(resolve(file), 'r');
  let data;
  try {
    const metadata = await handle.stat();
    if (!metadata.isFile() || metadata.size === 0 || metadata.size > MAX_IMAGE_BYTES)
      throw new ClientError('invalid_image', '图片不能为空且不能超过 20MB');
    data = await handle.readFile();
    if (!data.length || data.length > MAX_IMAGE_BYTES)
      throw new ClientError('invalid_image', '图片不能为空且不能超过 20MB');
  } finally {
    await handle.close();
  }
  const mime = data.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]))
    ? 'image/png'
    : data[0] === 255 && data[1] === 216 && data[2] === 255
      ? 'image/jpeg'
      : data.subarray(0, 4).toString() === 'RIFF' && data.subarray(8, 12).toString() === 'WEBP'
        ? 'image/webp'
        : '';
  if (!mime) throw new ClientError('invalid_image', '仅支持真实的 PNG、JPEG、WebP 图片');
  return `data:${mime};base64,${data.toString('base64')}`;
}

export async function preparePayload(spec, input) {
  if (!input || typeof input !== 'object' || Array.isArray(input))
    throw new ClientError('invalid_input', '任务参数必须是 JSON 对象');
  const payload = { ...input };
  const files = payload.input_files;
  delete payload.input_files;
  if (files !== undefined) {
    if (!Array.isArray(files) || files.some(file => typeof file !== 'string'))
      throw new ClientError('invalid_input', 'input_files 必须是本地图片路径数组');
    if (payload.input_images || payload.images || payload.image || payload.reference_image)
      throw new ClientError('invalid_input', '本地图片与远程参考图片请选择一种输入方式');
    if (
      files.length < (spec.minImages || 0) ||
      (spec.maxImages !== undefined && files.length > spec.maxImages)
    )
      throw new ClientError('invalid_input', '本地参考图片数量不符合此 Skill 的要求');
    const images = await Promise.all(files.map(imageData));
    if (spec.kind === 'describe') payload.image = images[0];
    else if (spec.kind === 'blend') payload.images = images;
    else payload.input_images = images;
    if (spec.maxImages && files.length > spec.maxImages)
      throw new ClientError('invalid_input', `此任务最多接受 ${spec.maxImages} 张参考图片`);
  }
  for (const key of Object.keys(payload))
    if (!spec.fields.includes(key))
      throw new ClientError('invalid_input', `此 Skill 不支持参数：${key}`);
  for (const field of spec.required || [])
    if (typeof payload[field] !== 'string' || !payload[field].trim())
      throw new ClientError('invalid_input', `缺少必填参数：${field}`);
  const images =
    payload.input_images ||
    payload.images ||
    (payload.image || payload.reference_image ? [payload.image || payload.reference_image] : []);
  if (
    !Array.isArray(images) ||
    images.some(item => typeof item !== 'string' || !item.trim()) ||
    images.length < (spec.minImages || 0) ||
    (spec.maxImages !== undefined && images.length > spec.maxImages)
  )
    throw new ClientError('invalid_input', '参考图片数量或格式不符合此 Skill 的要求');
  if (
    spec.toolName === '批量生图' &&
    payload.prompt_text.split(/\r?\n/).filter(line => line.trim()).length > 20
  )
    throw new ClientError('invalid_input', '批量生图最多接受 20 条描述');
  if (spec.toolName) payload.tool_name = spec.toolName;
  return payload;
}

export function createClient(spec, options = {}) {
  const providerBase = baseURL(spec.providers[spec.provider]);
  const environment = options.environment || process.env;
  const timeoutMs = options.timeoutMs || REQUEST_TIMEOUT_MS;

  async function request(base, path, { method = 'GET', body, secret, paid = false } = {}) {
    let response;
    try {
      response = await fetch(`${base}${path}`, {
        method,
        redirect: 'error',
        signal: AbortSignal.timeout(timeoutMs),
        headers: {
          ...(secret ? { Authorization: `Bearer ${secret}` } : {}),
          ...(body ? { 'Content-Type': 'application/json' } : {}),
          'X-MXAI-Skill': spec.slug,
        },
        ...(body ? { body: JSON.stringify(body) } : {}),
      });
    } catch {
      throw new ClientError(
        paid ? 'result_unknown' : 'network_error',
        paid ? '提交结果未知，请先查询最近任务，禁止直接重试收费操作' : '网络请求失败，请稍后重试',
      );
    }
    let result;
    try {
      result = await response.json();
    } catch {
      throw new ClientError(
        paid ? 'result_unknown' : 'invalid_response',
        paid ? '服务未返回可信结果，请先查询最近任务，禁止重复提交' : '服务返回了无效响应',
      );
    }
    if (!response.ok || result?.error || result?.error_type) {
      const message =
        typeof result?.message === 'string'
          ? result.message
          : typeof result?.error === 'string'
            ? result.error
            : `请求失败（HTTP ${response.status}）`;
      const insufficient = /积分不足|余额不足/.test(message);
      if (paid && response.status >= 500)
        throw new ClientError('result_unknown', '提交结果未知，请查询最近任务后核对，禁止自动重试');
      throw new ClientError(
        insufficient
          ? 'insufficient_credits'
          : response.status === 401 || response.status === 403
            ? 'api_key_invalid'
            : 'business_error',
        redact(message, [secret]),
        insufficient ? { type: 'open_url', url: spec.purchaseURL } : undefined,
      );
    }
    if (
      !result ||
      typeof result !== 'object' ||
      Array.isArray(result) ||
      Object.keys(result).length === 0
    )
      throw new ClientError(
        paid ? 'result_unknown' : 'invalid_response',
        paid ? '服务没有返回可信业务结果，请核对最近任务，禁止重复提交' : '服务响应缺少业务对象',
      );
    return result;
  }

  const authorization = createAuthorization(
    { provider: spec.provider, apiKeyEnv: spec.apiKeyEnv, keyURL: spec.keyURL },
    secret => request(providerBase, '/mcp/api/user', { secret }),
    environment,
  );

  async function authorizedRequest(path, options) {
    const secret = authorization.credential();
    return request(providerBase, path, { ...options, secret });
  }

  async function run(input) {
    if (!spec.endpoint) throw new ClientError('operation_not_allowed', '接入 Skill 不创建业务任务');
    const payload = await preparePayload(spec, input);
    const result = await authorizedRequest(spec.endpoint, {
      method: 'POST',
      body: payload,
      paid: payload.dry_run !== true,
    });
    if (payload.dry_run === true) return { ...result, status: 'quoted', provider: spec.provider };
    if (typeof result.serial_no !== 'string' || !result.serial_no)
      throw new ClientError('result_unknown', '服务没有返回任务编号，请核对最近任务，禁止重复提交');
    return { ...result, status: 'accepted', provider: spec.provider };
  }

  async function task(serial, waitSeconds = 0) {
    if (
      !/^[a-zA-Z0-9_-]{1,128}$/.test(serial || '') ||
      !Number.isFinite(waitSeconds) ||
      waitSeconds < 0 ||
      waitSeconds > 600
    )
      throw new ClientError('invalid_input', '任务编号或等待时长无效');
    const deadline = Date.now() + waitSeconds * 1000;
    do {
      const result = await authorizedRequest(`/mcp/api/task/${encodeURIComponent(serial)}`);
      if (![0, 1, 2, 3].includes(result.status))
        throw new ClientError('invalid_response', '服务未返回可信任务状态');
      if (result.status === 2 || result.status === 3 || Date.now() >= deadline)
        return { ...result, provider: spec.provider };
      await new Promise(resolveWait =>
        setTimeout(resolveWait, Math.min(POLL_INTERVAL_MS, Math.max(0, deadline - Date.now()))),
      );
    } while (true);
  }

  async function mjAction(serial, action) {
    if (
      spec.kind !== 'mj' ||
      !/^[a-zA-Z0-9_-]{1,128}$/.test(serial || '') ||
      !/^(U[1-4]|V[1-4]|REROLL)$/.test(action || '')
    )
      throw new ClientError('invalid_input', 'MJ 后续操作仅支持 U1-U4、V1-V4 和 REROLL');
    const result = await authorizedRequest('/mcp/api/mj/action', {
      method: 'POST',
      body: { serial_no: serial, action },
      paid: true,
    });
    if (!result.serial_no)
      throw new ClientError('result_unknown', 'MJ 未返回新任务编号，请核对任务记录');
    return { ...result, status: 'accepted', provider: spec.provider };
  }

  return {
    authStatus: authorization.verify,
    authVerify: authorization.verify,
    run,
    task,
    mjAction,
    account: () => authorizedRequest('/mcp/api/user'),
    tasks: () => authorizedRequest('/mcp/api/tasks'),
    models: () =>
      authorizedRequest(
        spec.provider === 'nano'
          ? '/mcp/api/tools'
          : ['mj', 'describe', 'blend'].includes(spec.kind)
            ? '/mcp/api/models?type=mj'
            : spec.kind === 'video'
              ? '/mcp/api/models?type=video'
              : '/mcp/api/models?type=image',
      ),
  };
}

async function main() {
  const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
  const spec = JSON.parse(await readFile(join(root, 'service.json'), 'utf8'));
  const client = createClient(spec);
  const [command, argument, extra] = process.argv.slice(2);
  let result;
  if (command === 'auth') {
    const methods = {
      status: client.authStatus,
      verify: client.authVerify,
    };
    if (!methods[argument])
      throw new ClientError(
        'invalid_command',
        '鉴权命令：auth verify / status；Key 创建和删除使用原接入页面',
      );
    result = await methods[argument]();
  } else if (command === 'run') {
    const text = argument?.startsWith('@')
      ? await readFile(resolve(argument.slice(1)), 'utf8')
      : argument;
    let input;
    try {
      input = JSON.parse(text);
    } catch {
      throw new ClientError('invalid_input', '请提供 JSON 参数或 @参数文件路径');
    }
    result = await client.run(input);
  } else if (command === 'task') result = await client.task(argument, Number(extra || 0));
  else if (command === 'mj-action') result = await client.mjAction(argument, extra);
  else if (['account', 'tasks', 'models'].includes(command)) result = await client[command]();
  else if (command === 'version') result = { version: spec.version, skill: spec.slug };
  else
    throw new ClientError(
      'invalid_command',
      '命令：auth、account、models、run、task、tasks、mj-action、version',
    );
  process.stdout.write(
    `${JSON.stringify(redact(result, [process.env.MX_AI_API_KEY, process.env.NANOAI_CN_API_KEY]), null, 2)}\n`,
  );
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  main().catch(error => {
    process.stdout.write(
      `${JSON.stringify(redact({ status: 'error', error: error.code || 'client_error', message: error.message, ...(error.action ? { action: error.action } : {}) }, [process.env.MX_AI_API_KEY, process.env.NANOAI_CN_API_KEY]), null, 2)}\n`,
    );
    process.exitCode = 1;
  });
}
