# 模板库索引（templates/）
> 版本：AIPO-TEMPLATES-1.21.0（14 场景 · **每模板中英双语**：中文规则正文 + EN Quick Reference 速查 + 任务句范式〔中文/EN 双语〕）
> **读法**：方法论 2.1（匹配模板）时，按内容类型查对应文件；每文件 = 识别信号/比例/版面骨架/**配色**/文字规则/避坑 **六要素**（v2.3 起新增「配色」行，强化高级感与色系纪律）。**全部是示例骨架、不是白名单**——参考后按方法论 4.1 八个部分自行组装，禁止照抄。通道无关：只写画面语言。
> **来源**：v2.3 各场景逻辑/结构/配色/避坑已吸收外部专业 skill（见 `生图技能参考/学习笔记-外部技能方法论沉淀.md`）：awesome-gpt-image-2（13 大类模板）、nanobanana2-skills（food/product/lifestyle）、clawic image-edit、guizang yingzao 等，均已**去通道化**提取。

| 文件 | 场景 | 识别信号 | 常用比例（各模板文件内含更全档位） |
|---|---|---|---|
| [poster.md](./poster.md) | T1 宣传海报 | 海报/宣传/活动/招募 | 3:4、9:16 |
| [cover-gzh.md](./cover-gzh.md) | T2 公众号封面 | 公众号/头图/文章配图 | 21:9 |
| [text-art.md](./text-art.md) | T3 文字图/日签 | 写字/标语/金句/日签 | 1:1、9:16 |
| [ui-infographic.md](./ui-infographic.md) | T4 UI/信息图 | UI/界面/图表/流程 | 16:9 |
| [ecommerce.md](./ecommerce.md) | T5 电商主图/成套图 | 电商/商品/详情/主图 | 1:1 |
| [avatar-wallpaper.md](./avatar-wallpaper.md) | T6 头像/壁纸 | 头像/壁纸/锁屏/背景 | 1:1、9:16、16:9 |
| [social-post.md](./social-post.md) | T7 社交媒体配图 | 小红书/微博/朋友圈/种草 | 3:4 |
| [festival.md](./festival.md) | T8 节日/节气图 | 中秋/春节/节气/新年/圣诞 | 3:4、1:1 |
| [editing.md](./editing.md) | T9 编辑/改图（i2i） | 改成/换背景/去掉/扩图/风格迁移 | 沿用原图 |
| [slides-teaching.md](./slides-teaching.md) | T10 演示/教学配图 | PPT/讲解/步骤图/示意 | 16:9 |
| [architecture.md](./architecture.md) | T11 建筑/空间效果图 | 室内/装修/户型/建筑外观 | 16:9、3:4 |
| [food.md](./food.md) | T12 美食图 | 菜品/探店/菜单/烘焙 | 4:3、1:1 |
| [comic-storyboard.md](./comic-storyboard.md) | T13 漫画/分镜 | 漫画/分镜/四格/故事板/多格 | 3:4、4:3 |
| [annotated-diagram.md](./annotated-diagram.md) | T14 标注图解/科普解剖 | 解剖图/标注图/结构图/图鉴 | 4:5、1:1 |

> 豁免：editing.md（T9 i2i 编辑）以"任务谱"替代"版面骨架"——编辑无版面，属合理形态。
> 不在清单内的场景（人像写真/风景/插画等题材类）不建版面模板——用方法论 4.1 八维骨架 + 4.2 术语表自由发挥即可。
> **v2.3 配色纪律**：每个模板均给出"推荐配色逻辑 + 禁区"——主色 ≤3 或限定色系、按场景气质取色（如美食按菜系、社媒按品牌原型、节日按应季色），避免过饱和、AI 油亮、廉价荧光。

---

## 案例语料

- **`../cases-unified.json`**：统一案例语料，供方法论 2.1 模板匹配与案例提炼使用；字段：id / source（取值 `master-541` 或 `peterroo-8k`）/ title / category / styles / scenes / language / quality / prompt / image / source_url。
- 提炼纪律：**去通道化**（模型专属写法不进模板）、**示例非白名单**、来源可溯（source / source_url）。
