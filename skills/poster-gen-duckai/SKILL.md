---
name: poster-gen-duckai
description: 生成图片/海报的标准流程：驱动本机 Edge 打开 duck.ai 输入提示词生图，提取成品保存为 JPG 并展示。触发词：生成图片、做海报、画一张、生成海报、AI 生图。
description_zh: Edge+duck.ai 生成图片/海报标准流程（JPG交付）
version: 1.0.0
allowed-tools: Bash
---

# 图片/海报生成标准流程（Edge → duck.ai）

孟姐指定的默认生图流程（2026-10-07 确认）：以后凡是要生成一张图或海报，走本流程。依赖 `edge-cdp-control` 技能（环境与踩坑细节看那边）。

## 交付要求（固定）

- 成品保存为 **JPG**（孟姐偏好 JPG，不要 PNG/SVG/HTML 预览页）
- 保存到当前工作区根目录，文件名 = 主题 + JPG，如 `元旦手机海报_duck.ai.jpg`
- 完成后必须 `present_files` 展示给用户
- 回复中简述：用的模型、尺寸、提示词要点

## 流程（6 步）

### 1. 确认 Edge CDP 就绪（有头模式）

```bash
env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY curl -s --noproxy "*" --max-time 3 http://127.0.0.1:9222/json/version | head -3
```

无响应 → 用 Bash 工具（run_in_background=true, dangerouslyDisableSandbox=true）运行 supervisor（`C:\Users\king\WorkBuddy\2026-10-07-14-23-13\edge_cdp_supervisor.py`，若换工作区则复制到新工作区），等 stdout 出现 `CDP port 9222 READY`。**必须是有头模式**（supervisor 默认），headless 会被 duck.ai 静默拦截。

### 2. 打开/切到 duck.ai 并清历史消息

每次生图前建议开新会话（避免上一次图片干扰提取）：导航到 `https://duck.ai/` 后用页面"新聊天记录"按钮（文本为"新聊天记录"）。首次进入若出现隐私弹层，坐标真实点击"继续"。

### 3. 组织提示词

duck.ai 会自动扩写，但要点要替孟姐说清楚：
- 类型与用途（手机海报/横版配图/贴纸等 → 决定竖横比例，手机海报写"竖版 9:16"）
- 主题、风格、配色（节日海报可指定红金等国风配色；无要求则不写，让模型发挥）
- 文案文字是否要出现在画面里（中文字易出错，重要文案建议生成底图后程序压字，参考 `ai-poster-hybrid` 技能）

### 4. 真实输入并发送（React 页面，禁止 JS 模拟提交）

```python
# 先 list_tabs 找回 duck.ai tab（daemon 可能漂移到新标签页），switch_tab 后再操作
pos = js("""(() => { const t = document.querySelector('textarea[name=user-prompt]');
  const r = t.getBoundingClientRect(); return JSON.stringify({x: r.x + r.width/2, y: r.y + Math.min(r.height/2,16)}); })()""")
click_at_xy(p['x'], p['y']); time.sleep(0.5)
type_text("<提示词>")
press_key("Enter")   # 真实回车发送；若没发出去，再真实坐标点击 button[aria-label="发送"]
```

### 5. 等生成完成并提取成品图

生成约 30~120 秒。轮询条件：页面文本不再含"正在生成"，且存在 `img` 满足 `naturalWidth > 500`（alt 通常为"选定的生成图像"，src 是 `data:image/...;base64`）。

```python
data = js("""(() => { const im = Array.from(document.querySelectorAll('img')).find(i => i.naturalWidth > 500); return im ? im.src : null; })()""")
# base64 解码写盘为 .jpg
```

### 6. 交付前的反馈修正（孟姐 2026-10-08 指定：标题字体优先 AI 烫金书法）

海报主标题不要直接用 Pillow 本地字体（孟姐嫌不好看）：优先按 `ai-poster-hybrid` 的「AI 烫金毛笔书法」方案（ImageGen 深红底 #8B0D0D + extract_gold_title.py 色键抠图），且需孟姐人工验字。

### 7. 交付

`present_files` 展示 JPG + 简述。若孟姐不满意，带修改意见在原会话继续发（duck.ai 支持基于上下文重生成/微调），重复第 5 步时注意页面上会有多张图，取**最后一张**大图。

### 8. 生成完成后关闭浏览器（孟姐 2026-10-08 指定，必做）

成品交付后关掉本次为生图打开的 duck.ai 标签页（优先只关自己开的 tab，不动孟姐自己的标签）；若是本流程自己启动的 supervisor/Edge 实例，一并停掉：

```python
# browser_use harness 内
for t in list_tabs():
    if 'duck.ai' in (t.get('url') or ''):
        close_tab(t)
```

再杀 supervisor/Edge（CDP 实例专用 profile 是 `C:\Users\king\.workbuddy\edge-cdp-profile`，不会误伤孟姐日常 Edge）：

```bash
taskkill //F //IM msedge.exe //FI "WINDOWTITLE eq *cdp*" 2>/dev/null  # 不可靠时改用：
# 用 wmic/PowerShell 按 command-line 含 edge-cdp-profile 或 remote-debugging-port=9222 过滤杀进程
```

注意：若孟姐明确说后续还要接着生成/改图，可以不关，下次生图前再关。

## 故障速查

| 现象 | 处理 |
|---|---|
| 消息发出无回复 | Edge 是 headless 或 UA 含 HeadlessChrome → 有头模式重启 supervisor |
| 发送无效/值在但不发 | 用了 JS 模拟事件 → 改真实 click_at_xy + type_text + Enter；若 press_key("Enter") 仍无效（2026-10-07 实测），先 click_at_xy 聚焦 textarea，再用 CDP `Input.dispatchKeyEvent`（keyDown/keyUp，key=Enter，code=Enter，windowsVirtualKeyCode=13，text=\r）发原生回车 |
| 「正在生成」卡住不消失 | 首次长生成可能 >5 分钟，后台持续轮询即可；若页面已有 naturalWidth>500 的 jpeg data URI 图，可直接提取不必等 busy 标志消失 |
| 提取到 imgCount=0 | daemon 漂移到了别的 tab → list_tabs + switch_tab 回 duck.ai |
| CDP 502 | 命令没去代理 → env -u http_proxy ... + NO_PROXY=localhost |
| 多张图混淆 | 生成前点"新聊天记录"，或按 DOM 顺序取最后一个大图 |
