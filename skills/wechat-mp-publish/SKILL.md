---
name: wechat-mp-publish
display_name: 公众号后台自动排版发布
display_name_en: WeChat MP Auto Publisher
description: 用 agent-browser 自动登录微信公众号后台并完成图文排版发布：填标题、写正文、按序插图、设封面、存草稿。当用户要求「发到公众号」「在公众号后台建文章」「把稿子排到公众号」时使用。已内置登录二维码提取、ProseMirror 输入、图片插入、封面设置的可行路径与全部踩坑记录。
description_zh: 用浏览器自动化完成微信公众号图文排版并存入草稿箱，把人工排版压成一条可复用脚本。能力覆盖：① 扫码登录与登录态持久化（二维码提取裁切、Cookie 备份与灌回，避免反复扫码）；② 进入编辑器的正确路径，避开直接打开编辑 URL 导致的空白页；③ 正文写入——绕过 ProseMirror 不吃键盘输入的限制，用光标重设加 execCommand 分段写入，并处理「文字接文字丢段首」等边界；④ 小标题批量加粗（选区必须落到文本节点级配合真实 Cmd+B，附成功判据与跳过已加粗段的保护）；⑤ 按序插图，直接写入隐藏 file input，不碰任何上传对话框；⑥ 设置 2.35:1 封面，从正文首图或素材库选取，按 fmt=jpeg 识别横版图，含弹窗坐标点击的全部坑；⑦ 保存并校验到草稿箱（type=77 才是草稿），发表环节绝不代点。
description_en: Automate WeChat Official Account article drafting via browser automation — title, body, in-order image insertion, cover selection and saving as draft, with verified paths for the ProseMirror editor and cover picker.
category: Productivity
version: 1.0.0
author: Bowen的AI实战笔记
---

# 公众号后台自动化发布

## 一、登录（最容易卡住的一步）

**可用 / 不可用的组合（实测）：**

| 方式 | 结果 |
|---|---|
| `agent-browser open <url>`（默认 headless） | ✅ 可用 |
| `--session-name <名>` | ✅ 可用（但保存文件常为空） |
| `--auto-connect` | ❌ 需用户 Chrome 开 `--remote-debugging-port` |
| `--profile <名\|目录>` | ❌ 页面停在 `about:blank` |
| `--headed` | ❌ 同样 `about:blank` |

所以**只能走扫码登录**，流程：

1. `agent-browser --session-name wechat-mp open "https://mp.weixin.qq.com/"`
2. 取二维码元素：`img.login__type__container__scan__qrcode`（用 `getBoundingClientRect()` 拿坐标）
3. 放大渲染后截图，裁切出干净二维码给用户扫：
   ```js
   document.documentElement.style.zoom='3';
   document.querySelector('img.login__type__container__scan__qrcode')
           .scrollIntoView({block:'center',inline:'center'});
   ```
   ```bash
   agent-browser screenshot /abs/path/qr.png
   ```
   再用 Pillow 按 rect 裁切 + 2× LANCZOS 放大 → ~840×840，清晰可扫。
4. 用户扫码后 `get url` 会出现 `/cgi-bin/home?...&token=<TOKEN>`，**token 每次登录都变，后续所有 URL 都要替换**。
5. ⚠️ **立刻备份 Cookie**：`agent-browser cookies get --json > auth.json`
   —— 守护进程空闲会重启，`--session-name` 的落盘不可靠，不备份就得再扫一次。
   用 `--plain` 格式（默认）拿不到 JSON，必须加 `--json`。

**再次开号时优先灌 Cookie，别急着出二维码**（Cookie 有效期通常在数周量级）：

```bash
# 从备份逐条灌回（cookies set 没有 --json 批量导入）
# 每条：agent-browser cookies set "<name>" "<value>" --domain mp.weixin.qq.com --path / \
#         [--httpOnly] [--secure] --expires <ts>
# 写完重新 open 首页，URL 里出现 token= 即为恢复成功
```

灌回后立刻 `cookies get --json` 再备份一次。token 每次都变，后续所有 URL 都要替换。

## 二、进入编辑器 + 结构与写正文

**⚠️ 不要直接 open 那个 `appmsg_edit_v2...&type=10` 的 URL——实测渲染出空白页**（顶部栏在、正文区全空，`#title` / `.ProseMirror` 都查不到）。正确入口是从首页点进去：

```js
// 1) 先开首页，确认登录
//    https://mp.weixin.qq.com/cgi-bin/home?t=home/index&lang=zh_CN&token=<TOKEN>
// 2) 点「新的创作 → 文章」
document.querySelector('.new-creation__menu-item').click();
// 3) 等 6~8 秒，URL 会变成 type=77&createType=0，此时编辑器才真正就绪
```

若 `!!document.querySelector('#ueditor_0 .ProseMirror')` 还是 false，**再等 8 秒**，不要急着判定失败。

- 关键元素（实测，与旧版文档一致）：
  - 标题：`#title`（TEXTAREA，上限 64 字）——设 `.value` 后要补派发 `input` + `change` 事件
  - 作者：`#author`
  - 正文：`#ueditor_0 .ProseMirror`（页面上有 3 个 `.ProseMirror`，**取 `#ueditor_0` 下的那个**）
  - 保存：`#js_submit`（文案「保存为草稿」）

**⚠️ 最大坑：`keyboard inserttext` / `type` 对 ProseMirror 完全无效**（不报错但不进字）。唯一可行的输入方式是 `document.execCommand('insertText')`。三条硬规则，缺一条就出错：

**① 每次插入前都要重设光标到正文末尾**（不能只在开头设一次）：

```js
var pm=document.querySelector('#ueditor_0 .ProseMirror');
pm.focus();
var s=window.getSelection(), r=document.createRange();
r.selectNodeContents(pm); r.collapse(false);
s.removeAllRanges(); s.addRange(r);
```

**② `\n` 与 `\n\n` 效果相同**——都会生成「正文段 + 空段」。所以全文一律用**单 `\n` 分段**，写完就没有空段，**不需要额外的清理脚本**（旧文档说 `\n` 只生成新段落，实测不成立）。

**③ 上一步也是纯文字插入时，本段必须前置一个 `\n`**：光标停在上一段末尾时首个字符会被**并进上一段**（表现为小标题凭空消失或粘在段尾）。

```python
if prev_kind == "text":
    insert_text("\n")      # 先断开
insert_text(payload)
```

「文字 → 图 → 文字」这种交替顺序没有这个问题（图片插入会自带新段落）。

**④ 长文本/含中文引号，走 base64 传参**，避免 shell 转义地狱：

```python
b64 = base64.b64encode(txt.encode("utf-8")).decode("ascii")
js = ("(function(){var t=decodeURIComponent(escape(atob('%s')));"
      "...document.execCommand('insertText',false,t);...})()") % b64
```

**⑤ `agent-browser eval` 的多语句代码必须包 IIFE**（`(function(){...})()`），否则报 `Illegal return statement`。

## 三、插图（不用碰任何对话框）

编辑器页有隐藏的 `input[type=file]`（accept 含 png），**直接把文件塞进去即可，图片会插入到当前光标位置**：

```bash
agent-browser upload "input[type=file]" /abs/path/card.png
sleep 8   # 等上传完成
```

所以「文字 → 图 → 文字 → 图」的顺序可以完全脚本化。把整段逻辑写成 Python 脚本一次跑完，比逐条命令快得多。

## 四、小标题加粗（唯一可行路径）

**⚠️ 两条路都会失败：**

- `document.execCommand('bold')`：DOM 上**当时**能看到 `<b>`，但下一次读 DOM 就被 ProseMirror 按内部 state 回退了（实测 `font-weight` 恒为 400）。
- 点工具栏 `.edui-for-bold`：同样无效；即使把选择与 `click()` 放在同一个 eval 里也不行。

**唯一可行：把选区选到「文本节点级」，再用真实键盘按 `Cmd+B`。**

关键差别是选区粒度——`selectNodeContents(段)` 会被 ProseMirror 当成节点选择，mark 不生效；必须选中段内**文本节点**的起止偏移：

```js
var tns=[], w=document.createTreeWalker(c,NodeFilter.SHOW_TEXT,null), n;
while(n=w.nextNode()){ if(n.nodeValue&&n.nodeValue.length) tns.push(n); }
var s=window.getSelection(), r=document.createRange();
r.setStart(tns[0],0);
r.setEnd(tns[tns.length-1], tns[tns.length-1].nodeValue.length);
pm.focus(); s.removeAllRanges(); s.addRange(r);
```

```bash
sleep 1                                            # 留一拍让 ProseMirror 同步选区
agent-browser press "Meta+b"
sleep 1
```

成功标志：该段 innerHTML 变成
`<span leaf=""><span textstyle="" style="font-weight: bold">标题</span></span>`。

校验用 `/font-weight:\s*bold/.test(c.innerHTML)`，**不要**用 `c.querySelector('b,strong')`——这个编辑器产出的是带 style 的 span，没有 b/strong 标签。

批量处理时每个标题都要 `eval 选段 → sleep 1 → press Meta+b → sleep 1`，且要跳过已加粗的段，否则会二次切换把加粗取消掉。

## 五、设置封面

**封面只能从「正文里已有的图片」或「素材库」里选**，不能凭空上传给封面位。

- 所以想让封面用横版图，就**先把横版图插到正文最前面**（光标放 `setStart(pm,0)` 再 upload），再进封面流程选它。
- 平台封面比例固定 **2.35:1**（消息列表）。建议直接做成 **1080×460**（正好 2.35）的横版 JPG。
- 流程（实测修正版）：
  1. **先把横版封面插到正文最前面**（光标 `setStart(pm,0)` 再 `upload`），这样它同时进素材库。封面图要先用 Pillow 转成 `.jpg`（封面位只认 jpg/gif，别喂 png）。
  2. **用真实鼠标点击** `.js_cover_btn_area`（235×100 的拖拽区）中心：先 `eval` 拿 `getBoundingClientRect()` 算中心点，再 `mouse move/down/up`。
     ⚠️ 对 `.js_share_type_none_image`（里面的文案 span）做 JS `.click()` **不会**弹出菜单，必须用真实鼠标点在 `.js_cover_btn_area` 上。
  3. 弹出的菜单是 **`ul.pop-opr__list li`**，共 4 项：`从正文选择可选视频封面 / 从图片库选择 / 微信扫码上传 / AI 配图`。
     ⚠️ 菜单会**盖在封面区上方**，所以点完封面区后如果 `elementFromPoint` 命中的是 `UL.pop-opr__list`，说明菜单已经开了，别再重复点。用 `textContent`（不是 `innerText`）+ `getBoundingClientRect()` 列出可见项再点。
  4. 点「从图片库选择」→ 弹窗 `选择图片`，分页签「最近使用 / 我的图片 / 未分组 / AI 配图」。缩略图 `.weui-desktop-img-picker__img-thumb` 是 **110×110 的正方形 + background-image**，**六列一行**，每页 30 张。最新上传的图卡在第 1 行前几位。
     ⚠️ 缩略图是正方形裁切，**不能靠长宽比认出横版封面**；**靠 `getComputedStyle(el).backgroundImage` 里的 `fmt=jpeg` 判断**（图卡通常都是 png，只有 jpg 转出来的封面是 jpeg）。
  5. 选中后（缩略图或其父级会加 `selected`）点底部 `下一步`（`.weui-desktop-btn_primary`）→ 进入「编辑封面 2.35:1」→ 点 `确认`。
  6. 成功判据：封面区显示封面缩略图，左侧内容管理卡片预览同步更新。
- ⚠️ **视口必须开大（如 1440×1300）**，否则弹窗底部按钮在可视区外，`getBoundingClientRect()` 返回 0×0，点不到。渲染图卡时如果改过视口（如 1080×460），**回来操作编辑器前一定要恢复**。

## 六、坐标点击的通用教训

`agent-browser screenshot` 输出的宽度固定 1080，**与 CSS 视口不等比**。所以**不要用截图里的坐标去点**。一律：

1. `eval` 拿 `getBoundingClientRect()` 得到 CSS 坐标
2. 用 `agent-browser mouse move/down/up` 点击，或
3. 用 JS `element.click()` / `dispatchEvent`

## 七、落库与验证

- 草稿箱列表 URL：`https://mp.weixin.qq.com/cgi-bin/appmsg?begin=0&count=10&type=77&action=list_card&token=<TOKEN>&lang=zh_CN`
  （**`type=77` 才是草稿箱**，`type=10` 会得到空列表——曾被这个误导以为没保存成功）
- 保存成功判据：编辑器左侧「历史版本」出现一行「手动保存 + 时间」，且草稿箱能看到卡片与封面缩略图。
- **群发/发表不可撤回**：做到草稿即止，让用户自己点发表。

## 八、完整链路示例

一次跑通的典型配置：

1. 标题 + 约 1,300 字正文 + 5 张竖版图卡 + 1080×460 横版封面 → 草稿箱可见
2. 第二次迭代：1,700+ 字正文 + 8 个加粗小标题 + 封面（前置在正文首图）+ 2.35:1 封面 → 草稿箱可见

驱动器脚本模式：`write_body.py`（text/img 交替 + 每次重设光标 + 文字接文字前置 `\n`），把整条编排写成一个 Python 脚本一次执行，比逐条 shell 命令稳定得多。
