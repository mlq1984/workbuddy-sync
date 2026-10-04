---
name: poster-maker
display_name: 海报生成器（社媒封面/分享卡/OG图）
display_name_en: Poster Maker (social covers, share cards, OG images)
description: 生成海报/做海报/公众号封面/小红书配图/朋友圈配图/OG图/分享卡/头图/横幅/banner — social-ready posters, covers and share cards with big-type layouts, brand gradients and platform size specs. Pixel-exact, offline, no browser.
description_zh: 生成社媒视觉物料:海报、公众号封面、小红书/朋友圈配图、OG 分享卡、头图、横幅。大字排版 + 品牌渐变,像素精确、离线毫秒级出图,内置封面/OG/方图等现成模板与尺寸规范。
description_en: Generate social-ready posters, article covers, OG/share cards and banners with big-type layouts and brand gradients. Pixel-exact, offline, milliseconds per render, with ready-made templates and platform size specs.
category: image
version: 1.2.0
author: AutoClaw
---

# 海报生成器

为社媒与营销场景产出视觉物料:海报、公众号封面、小红书/朋友圈配图、OG 分享卡、横幅。本技能在通用渲染引擎之上沉淀了**海报排版规范、平台尺寸表和视觉质量清单**,照着做就能出可发布的图。

## 何时使用

- 用户要"做一张图":海报、封面、配图、分享卡、头图、banner、活动视觉
- 给文章/产品/活动配一张有文字的视觉图(精确文字、品牌色、排版要求)
- 不适用:发票/报价单等文档(用 invoice-maker);纯照片级艺术图(用平台 AI 生图);任意自定义图形(用 code2media 通用技能)

## 平台尺寸速查

| 场景 | 尺寸 | 模板 |
| :--- | :--- | :--- |
| 小红书封面(3:4 占屏最大) | 1080 × 1440 | `social-post.html` 改尺寸 |
| 朋友圈/通用方图 | 1080 × 1080 | `social-post.html` |
| 公众号首图封面 | 900 × 383 | `cover.html` |
| 博客/官网 OG 分享卡 | 1200 × 630 | `og-card.html` |
| 竖版海报(印刷感) | 1080 × 1440 | 改方图模板尺寸即可 |
| 视频封面 | 1280 × 720 | 改封面模板尺寸即可 |

> 小红书只支持 1:1、3:4、4:3 三种比例,3:4 观感最好;多图笔记的配图先统一尺寸,否则系统自动补白边(整套一次出:见下方「多图系列笔记」)。

## 场景速查

不同场景的构图、配色和视觉重心完全不同,先对号入座(信息层级与易错点详见 `@references/scenario-playbook.md`):

| 场景 | 构图 | 配色 | 第一视觉 |
| :--- | :--- | :--- | :--- |
| 促销/电商 | 左对齐或强分裂 | 红橙黄高饱和 | 折扣/价格数字 |
| 活动/会议 | 居中 | 主题色+深底 | 活动名 |
| 招聘 | 左对齐 | 品牌蓝/绿 | 岗位名+薪资 |
| 餐饮/美食 | 图左文右 | 暖色(红橙黄) | 菜品实拍 |
| 节日/节气 | 居中 | 传统配色 | 节日符号+大字 |
| 知识/课程 | 左对齐 | 低饱和+强调色 | 收益式标题 |
| 地产/政务 | 居中 | 蓝金/红金/深灰 | 机构名或主标 |
| 品牌/发布 | 大面积留白 | 深色高级感 | 产品本身 |
| 科技/数码发布 | 钩子标题+数字卡片+条形图 | 深色底+单一强调色 | 钩子标题 |

## 工作流程

1. **定场景、定骨架**:先确定海报场景(促销/活动/招聘/节日…),按上方速查表定构图与配色。`templates/` 里的模板是**结构骨架与起点,不是默认皮肤**——布局可以借,但配色、字体气质、构图轴、强调手法必须按本次内容与品牌重新决策,别把内置模板的默认样式原样交付(千篇一律的"模板脸"比单页丑更伤观感)。输出稳定性由语法铁律与对齐检查保证(见质量清单),视觉创造力该放开就放开。
2. **写 HTML**:语法三条铁律(详见 `@references/syntax-guide.md`):
   - Tailwind 工具类写 **`tw` 属性**(`class` 不编译 Tailwind);
   - 用 v4 规范名(渐变 `bg-linear-to-br`,不是 `bg-gradient-to-br`);
   - 根元素撑满画布 `tw="w-full h-full ..."`。
3. **渲染**:
   ```bash
   node "<技能目录>/scripts/render.mjs" --html poster.html -o poster.png --width 1080 --height 1080
   ```
4. **过质量清单**(下方),不满意改了重跑——渲染是毫秒级的。渲染脚本会在 stderr 提前 Warning 两类高发的静默失败:`class` 里误写 Tailwind 工具类、模板含中文但没探测到 CJK 字体——看到 Warning 先修再交付。

## 海报视觉质量清单

- **文字层级 ≤ 3 级**:主标题(最大)/副标题/说明文字,一眼能分清主次;主标题占画面高度 ≥ 1/5
- **留白要狠**:内边距不小于画布短边的 5%(如 1080 宽至少 54px);元素之间用 `gap`/`mt` 拉开呼吸感
- **对比度**:文字与背景必须有足够对比;浅色文字配深色渐变,或深色文字配浅色底;文字压图三招(挪干净处/背景压暗/色块描边)见场景手册
- **配色 ≤ 3 种**:主色+辅助色+强调色;拿不准就用品牌色的深浅渐变家族
- **分组要明显**:相关元素贴近、无关元素拉远,组间距差距 ≥ 2 倍,一眼扫出信息块
- **中文不斜体**(斜体在无衬线中文里很丑),强调用加粗/变色/字号
- **一图一重点**:不要把所有信息塞进一张图;胶囊标签 ≤ 3 个
- **品牌一致性**:有品牌色/Logo 就放角标位,颜色用品牌色的渐变家族
- **渲染后目检样式**:某元素样式没生效(字号/间距突然不对),先查是否把工具类写进了 `class`——工具类必须写 `tw`,`class` 里的会静默失效不报错(脚本会 Warning 提示)
- **多列对齐必须目检**:价目表/表格/图文左右栏这类多列版式,渲染后逐列检查起点是否对齐——flex 子项默认可收缩,定宽列要加 `shrink-0`(tw 内)或内联 `style="width:..px;flex-shrink:0"`,否则总宽超出容器时列被静默压窄,这是列错位的最高发原因
- 字体:`style="font-family:msyh,NotoSansCJK-Regular,wqy-zenhei"`,离线环境 Emoji 保持纯文本

## 批量与变体

一个活动要 5 种尺寸、10 个城市的本地化海报?同一模板改文案/尺寸循环调用脚本即可,输出确定性保证同模板永远同品质。渲染完可用 `identify`(ImageMagick)或直接看文件大小做粗校验。

## 多图系列笔记

小红书多图笔记要求全套同尺寸同风格。用 `templates/social-post-series.html`(页眉品牌位、右上篇章胶囊、右下页码都是 `{{TOKEN}}` 占位)+ `scripts/render-series.mjs`,数据驱动一次出整套:

```bash
node "<技能目录>/scripts/render-series.mjs" --template "<技能目录>/templates/social-post-series.html" \
  --data series.json --outdir out/ --width 1080 --height 1440
```

- `series.json` 写法见同目录示例 `social-post-series.json`:`shared` 放全系列相同字段(品牌/篇章胶囊/页脚,**配色也走数据**——`BG_TOP/BG_MID/BG_BOT` 背景渐变与 `ACCENT/ACCENT_SOFT` 强调色),`pages[]` 放每页的标题与内容;`{{PAGE}}/{{TOTAL}}` 页码自动按 `01 / 04` 风格填充
- **"同一根模板"约束的是一个系列之内**:同系列必须复用同一根模板与同一组配色 token,只换标题区/内容区——系列内风格漂移比单页丑更伤账号;**不同系列、不同品牌之间则必须换骨架换配色**(换配色直接改数据即可,换明暗底色类型就改模板骨架),别让每个账号都长一个样
- 每页会同时落一份填好的 `.html`;单页不满意可直接改它,再用 `render.mjs` 单独重渲这一页

## 环境要求

Node.js >= 20.19;首次运行自动安装 takumi-js/takumi-pdf(一次性,需网络)。容器内中文需字体包(`font-noto-cjk`)。需要完全自定义的非海报图形时,用 `code2media` 通用技能。
