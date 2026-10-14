---
name: wxml-preview
description: "Preview WeChat Mini Program pages (WXML/WXSS) as standalone HTML in a phone-frame mockup. Use when the user wants to view/preview/browse a wxml page, check mini program UI effects, or render wx:for/wx:if templates without WeChat DevTools."
description_zh: "微信小程序页面预览：把 WXML/WXSS 转成手机外框 HTML 预览，无需微信开发者工具"
version: 1.0.0
allowed-tools: Read,Write,Bash
---

# WXML Preview — 小程序页面预览技能

把微信小程序页面（`.wxml` + `.wxss`）转换为独立 HTML 文件，带手机模拟器外框，可直接在浏览器/内置预览面板中查看 UI 效果。

## 何时使用

- 用户说"预览/浏览/看看这个 wxml / 小程序页面效果"
- 用户想不装微信开发者工具就检查小程序 UI
- 生成小程序代码后需要视觉验证

## 使用方法

转换脚本：`scripts/wxml2html.py`（依赖 beautifulsoup4，环境已装）

```bash
PYTHON="C:/Users/king/.workbuddy/binaries/python/versions/3.13.12/python.exe"
SCRIPT="C:/Users/king/.workbuddy/skills/wxml-preview/scripts/wxml2html.py"

"$PYTHON" "$SCRIPT" pages/home/home.wxml \
    --wxss pages/home/home.wxss \
    --data /tmp/page-data.json \
    --title "首页" \
    --out preview_home.html
```

参数：
- `wxml`（必填）：目标页面 .wxml 路径；同名 .wxss 会自动查找
- `--data`：页页面 data 的 JSON mock 数据，用于渲染 `{{表达式}}`、`wx:for`、`wx:if`
- `--out`：输出 HTML 路径（默认同名 `_preview.html`）
- `--title`：手机壳标题栏文字

## 工作流程

1. **准备 mock 数据**：读取对应页面的 `.js` 文件，从 `data: {...}` 和 `setData(...)` 中提取数据；如页面 require 了 `mockData.js` 等模块，把数组/对象手动转写为等价 JSON 文件。
2. **运行转换脚本**，得到 HTML。
3. **用 present_files 展示 HTML**（会自动打开内置预览面板）。

## 转换规则-supported

| WXML | HTML |
|------|------|
| `<view>` / `<text>` / `<image>` | `div` / `span` / `img` |
| `<scroll-view>` / `<swiper>` / `<swiper-item>` | `div`（静态化） |
| `wx:for` + `wx:for-item/index` | 展开为重复节点 |
| `wx:if / wx:elif / wx:else` | 按 mock 数据求值保留/删除 |
| `{{ a.b }}`、`{{list[0].name}}`、`{{a?b:c}}`、`{{a==b}}`、`{{'str'}}`、`{{a+b}}` | 求值替换 |
| `rpx` 单位 | px（÷2，375px 视口） |
| `page` 选择器 | `.phone-body` |
| `bindtap` / `data-*` 属性 | 移除（静态预览） |

## 限制（诚实告知用户）

- 交互（点击事件、页面跳转）不执行，纯静态预览
- 复杂表达式（函数调用、filter、嵌套三元）可能无法求值，会输出空字符串
- `wx.request` 动态数据需用 mock JSON 替代
