// 复用网站已经生成的 API Key，不创建设备凭证、不请求新增授权接口。
const API_KEY_ENVIRONMENTS = Object.freeze({ mxai: 'MX_AI_API_KEY', nano: 'NANOAI_CN_API_KEY' });

export class ClientError extends Error {
  constructor(code, message, action) {
    super(message);
    this.name = 'ClientError';
    this.code = code;
    this.action = action;
  }
}

/** 同产品的所有 Skill 读取同一环境变量；不同产品不能偷偷借用对方的 Key。 */
export function createAuthorization(
  { provider, apiKeyEnv, keyURL },
  requestAccount,
  environment = process.env,
) {
  if (API_KEY_ENVIRONMENTS[provider] !== apiKeyEnv)
    throw new ClientError('invalid_configuration', 'Skill 的产品与 API Key 配置不匹配');

  function credential() {
    const value = environment[apiKeyEnv]?.trim();
    if (!value)
      throw new ClientError(
        'api_key_required',
        `请在宿主环境配置 ${apiKeyEnv}，可在现有接入页面创建 Key`,
        { type: 'open_url', url: keyURL },
      );
    // Key 的有效性由已有账户接口验证，不按前缀、长度或字符猜测。
    return value;
  }

  async function verify() {
    const account = await requestAccount(credential());
    return { status: 'verified', provider, account };
  }

  return { credential, verify };
}
