---
name: edge-cdp-control
description: 通过 CDP 控制本机 Edge 浏览器（headless 或已运行实例）。适用于网页自动化、表单填写、截图、数据抓取。触发词：控制Edge、Edge浏览器、浏览器自动化、打开网页、网页截图。
description_zh: 控制 Edge 浏览器自动化（导航/点击/输入/截图/抓数据）
version: 1.0.0
allowed-tools: Bash
---

# Edge 浏览器控制（browser-use + CDP，Windows）

用 `browser-use` CLI（Python 包）通过 CDP 控制 Edge。本机已验证可用（2026-10-07）。

## 关键环境坑（Windows 本机特有，必读）

1. **代理拦截 localhost**：环境注入了 `http_proxy/https_proxy=http://127.0.0.1:51506`，会把 CDP 的 localhost 连接劫持成 `HTTP 502`。**每条 browser-use / curl 命令必须去掉代理变量**：
   ```bash
   env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
   NO_PROXY="localhost,127.0.0.1,::1" no_proxy="localhost,127.0.0.1,::1" \
   BU_CDP_URL="http://127.0.0.1:9222" <命令>
   ```
2. **Edge 进程会被会话清理**：普通 `&` 后台启动的 Edge 在 shell 退出后被杀。持久方案是用 supervisor 脚本（见下）以 run_in_background + 非沙箱方式运行，它会自动重启挂掉的 Edge。
3. **默认 User Data 目录不能用**：Edge 的 DevTools 调试要求非默认 `--user-data-dir`；且原配置目录带账号密钥解密报错。使用专用目录 `C:\Users\king\.workbuddy\edge-cdp-profile`。
4. **沙箱隔离 localhost**：沙箱内 bash 可能连不上 127.0.0.1:9222，启动 Edge / 验证端口时用 `dangerouslyDisableSandbox=true`。

## 组件位置

- Edge 可执行文件：`C:\Program Files (x86)\Microsoft\Edge\Application\154.0.4258.53\msedge.exe`（版本号可能变化，用 `ls "/c/Program Files (x86)/Microsoft/Edge/Application/"` 确认）
- browser-use CLI：`C:\Users\king\.workbuddy\binaries\python\versions\3.13.12\python.exe -m browser_use`
- Supervisor 脚本：`C:\Users\king\WorkBuddy\2026-10-07-14-23-13\edge_cdp_supervisor.py`（启动 headless Edge:9222 并守护）

## 标准流程

### 1. 确认/启动 Edge CDP

```bash
env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY curl -s --noproxy "*" http://127.0.0.1:9222/json/version 2>/dev/null | head -3
```

若端口无响应，用 Bash 工具（run_in_background=true, dangerouslyDisableSandbox=true）运行：
```
C:\Users\king\.workbuddy\binaries\python\versions\3.13.12\python.exe <workspace>\edge_cdp_supervisor.py
```
等 stdout 出现 `CDP port 9222 READY`。

### 2. 执行自动化（heredoc 传 Python，helpers 已预导入）

```bash
env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
NO_PROXY="localhost,127.0.0.1,::1" no_proxy="localhost,127.0.0.1,::1" \
BU_CDP_URL="http://127.0.0.1:9222" \
"C:\Users\king\.workbuddy\binaries\python\versions\3.13.12\python.exe" -m browser_use <<'PY'
new_tab("https://example.com")   # 每个任务首次导航用 new_tab(url)
wait_for_load()
fill_input("#kw", "搜索词")       # 填输入框
js("document.querySelector('#su').click()")  # 坐标点击失败时用 JS click 兜底
wait_for_load()
print(page_info())                # {url, title, w, h, ...}
path = capture_screenshot()       # 返回截图 png 本地路径
PY
```

常用 helpers：`new_tab(url)` `goto_url(url)` `page_info()` `capture_screenshot()` `click_at_xy(x,y)` `type_text` `fill_input(sel,text)` `press_key(k)` `js(code)` `cdp(method, **params)` `wait_for_load()` `wait_for_element(sel)` `list_tabs()` `switch_tab(t)` `close_tab(t)`

### 3. 提取数据示例

```python
js("Array.from(document.querySelectorAll('.result h3')).map(e=>e.textContent).slice(0,10)")
```

## 重要教训（2026-10-07 duck.ai 实测）

1. **headless 会被网站静默拦截**：headless=new 下 UA 带 `HeadlessChrome`，duck.ai 能收消息但永不生成回复（无报错）。改用**有头模式**（去掉 `--headless=new` 参数）后一切正常。supervisor 脚本默认已改为有头。
2. **React 应用别用 JS 模拟提交**：`fill_input`/`js(el.click())`/dispatch KeyboardEvent 只写入 DOM 值，React 状态不同步，发送无效。正确姿势：`getBoundingClientRect` 取坐标 → `click_at_xy` 真实点击聚焦 → `type_text` 真实键盘输入 → `press_key("Enter")` 真实回车发送。
3. **daemon 会漂移到别的 tab**：supervisor 重启后 harness 默认附着到 Edge 新标签页（ntp.msn.com）。每次操作前先 `list_tabs()` 找目标 URL 的 targetId 再 `switch_tab()`。
4. **duck.ai 生图成品提取**：结果图是 `img[src^=data:image]`（alt="选定的生成图像"），在页面里 `js()` 取 src 后 base64 解码存盘即可，`naturalWidth>500` 过滤缩略图。首次进入需点"继续"同意隐私政策。

## 注意

- 首次导航用 `new_tab(url)`，同一站点后续用 `goto_url`；保持每任务一个 tab。
- 坐标点击前必要时先滚动；`getBoundingClientRect` 需 `returnByValue=True` 且注意返回可能是空 dict（元素不可见）。
- press_key("Enter") 在百度不一定触发搜索，用按钮 JS click 更稳。
- 需要操作孟姐真实登录态（Cookie/账号）时：不能用 headless 调试实例，需让用户以 `--remote-debugging-port=9222` 重启真实 Edge（会提示先关闭现有 Edge），或用 `browser-use` 的 profile 方案。
