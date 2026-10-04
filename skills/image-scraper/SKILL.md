---
name: image-scraper
description: "为内容创作爬取高清配图（百度图片/Wallhaven/Unsplash），支持4K原图下载"
version: 1.0.0
display_name: "图片爬虫"
display_name_en: "Image Scraper"
description_zh: "为内容创作爬取高清配图（百度图片/Wallhaven/Unsplash），支持 4K 原图下载"
description_en: "Scrape high-res images from Baidu Images, Wallhaven and Unsplash for content creation, up to 4K originals."
---

# 高清图片爬虫

为内容创作爬取 4K 高清配图。支持多个图片来源，按优先级自动切换。

**优先级：百度图片搜索（主） → Wallhaven（备） → Unsplash（备）**

---

## 图片规格目标

- **竖图**：高度 2000px 以上（越高越好）
- **横图**：宽度 2000px 以上
- **方图**：宽高均 1500px 以上
- **风格**：真人摄影风格，避开动漫/暴露/擦边内容

### 尺寸预设速查表

| 预设 | 横图 (landscape) | 竖图 (portrait) | 方图 (square) | 备注 |
|------|----------------|----------------|--------------|------|
| `1080p` | 1920×1080 | 1080×1920 | 1080×1080 | 入门级 |
| `1080+` | 2560×1440 | 1440×2560 | 1440×1440 | 强化爬取（&z=7） |
| `1.5K` | 2250×1266 | 1266×2250 | 1500×1500 | 中端 |
| `2K` | 2560×1440 | 1440×2560 | 2000×2000 | 2K 级别 |
| `4K` | 3840×2160 | 2160×3840 | 3840×3840 | 高清（默认） |
| `8K` | 7680×4320 | 4320×7680 | 7680×7680 | 超高清 |

> `1080+` 会强制加 `&z=7` 参数，告诉百度优先返回近期高质量图片，爬取效果显著优于普通模式。

## 存储路径

> **重要**：脚本默认输出到当前工作目录下的 `image-scraper-downloads/` 文件夹。
> 可用 `--output` 自定义路径（支持绝对路径和相对路径）。

```
# 默认（当前工作目录/image-scraper-downloads/）
python3 scripts/baidu_image_scraper_v8.py --keyword "JK少女" --count 100

# 自定义输出目录
python3 scripts/baidu_image_scraper_v8.py --keyword "JK少女" --count 100 --output ./my-images/
```

---

## 一、百度图片搜索（主选）

> 图源最丰富，包含 B站、得物、大众点评、爱奇艺等高质量 CDN 内容，竖图可达 **4K+**，横图可达 **5K+**

**缺点**：需要浏览器渲染提取图片 URL，无法直接 curl

### 推荐脚本（v8 重构版，一键运行）

```bash
# ── 单关键词爬取（最常用）────────────────────────
# 目标自动 × 1.2，内部 buffer；关键词不够自动换备用词；下载完自动去重+删低质量
# 默认输出到 ./image-scraper-downloads/
python3 scripts/baidu_image_scraper_v8.py --keyword "JK少女" --count 100
python3 scripts/baidu_image_scraper_v8.py --keyword "JK少女" --count 200 --output ./my-images --z 7 --scroll 20
python3 scripts/baidu_image_scraper_v8.py --keyword "JK少女" --count 100 --ratio portrait --z 7
python3 scripts/baidu_image_scraper_v8.py --keyword "4K风景" --count 50 --ratio landscape

# ── 多关键词补充爬取 ─────────────────────────────
# 自动换关键词，直到达到目标数量
python3 scripts/baidu_image_scraper_v8.py --keywords "JK制服 少女" "JK 高清美女" "日本JK制服" --count 500 --output ~/photos

# ── 从已有链接文件下载 ─────────────────────────────
python3 scripts/baidu_image_scraper_v8.py --from-file links.json --output output --count 100

# ── 清理（手动）─────────────────────────────────
python3 scripts/baidu_image_scraper_v8.py --clean --output ~/photos
```

**前置要求**：`agent-browser` 命令可用（WorkBuddy 内置）

**v8 核心改进（重构版）**：

| 改进 | 说明 |
|------|------|
| **移除 hover** | 百度新版不再生成 `tn=download` 链接，hover 逻辑已废弃 |
| **直接提取 objurl** | 从 `.img-cell-w6C5O` 的 `data-show-ext` 属性直接提取原图 URL |
| **更快更稳定** | 无需等待 hover 触发，数据已在 DOM 中 |
| **全图源支持** | 支持抖音、B站、得物等所有来源的原图下载 |
| 原子计数器 | `AtomicCounter` 类，线程安全的文件名生成 |
| 实时进度 | 每 20 张打印一次进度 |
| 哈希去重 | 下载前 MD5 校验，避免重复下载 |
| 分批下载 | 100 张/批，边提取边下载 |
| 自动后处理 | MD5去重 → 删除低质量图 → 重命名编号 |

**技术流程（v8 新方案）**：打开搜索页 → 最大化窗口 → 等待图片网格渲染 → 滚动加载 → 直接从 `.img-cell-w6C5O` 的 `data-show-ext` 属性提取 `objurl`（原图URL）→ 立即并发下载每一批 → MD5 哈希去重

> **核心原则：直接下载 `objurl`（原图 URL）**
> `objurl` 是百度图片搜索结果中的原图地址，包含在 `data-show-ext` JSON 属性中。
> 抖音等来源的 `objurl` 可以直接下载（经过百度 CDN 缓存）。

### 技术要点

| 项目 | 说明 |
|------|------|
| **数据位置** | `.img-cell-w6C5O` 元素的 `data-show-ext` 属性（JSON 格式） |
| **原图 URL** | `data-show-ext.objurl` |
| **其他字段** | `url`（缩略图）、`title`（标题）、`cs`、`setsign` |
| 抖音图片 | 直接使用 `objurl` 下载，无需特殊处理 |
| JS 引号 | 提取 JSON 属性时自动解析 |
| 浏览器窗口 | 每次打开后最大化 |
| 链接来源 | `miaobi-lite.cdn.bcebos.com`（百度 CDN）、`douyinpic.com` 等 |

### 图源质量排名

#### 竖图（portrait）推荐

| 排名 | 来源 | 典型分辨率 | 质量 | 备注 |
|------|------|-----------|------|------|
| 🥇 | `p1.meituan.net`（美团CDN） | **4480×6720** | 极高 3MB+ | 来源极丰富 |
| 🥈 | `q1.itc.cn` / `q8.itc.cn`（爱奇艺CDN） | **3000×4000** | 高 | 竖图横图均有 |
| 🥉 | `b0.bdstatic.com`（百度CDN） | 2000×2667 | 高 | 竖图来源多 |
| 4 | `pic.rmb.bdstatic.com`（贴吧/百科CDN） | 1080×1621 | 高 | 稳定，直链 |
| 5 | `image-cdn.poizon.com`（得物CDN） | 1280×1920 | 高 | 稳定 |
| 6 | `dpfile.com`（大众点评CDN） | 1440×1920 | 高 | 竖图方图均有 |
| 7 | `photo.tuchong.com`（图虫摄影） | 1080×1620 | 中高 | 真实摄影风格 |

#### 横图（landscape）推荐

| 排名 | 来源 | 典型分辨率 | 质量 | 备注 |
|------|------|-----------|------|------|
| 🥇 | `q4.itc.cn`（爱奇艺CDN） | **5307×4009** | 极高 | 最佳横图来源 |
| 🥈 | `5b0988e595225.cdn.sohucs.com`（搜狐CDN） | **3500×2214** | 高 | 质量极高 |
| 🥉 | `b0.bdstatic.com`（百度CDN） | 2560×1440 | 高 | 横图约2000px |
| 4 | `i0.hdslb.com` / `i1.hdslb.com`（B站CDN） | 2560×1440 | 高 | 稳定 |
| 5 | `dpfile.com`（大众点评CDN） | 3070×2048 | 高 | |

#### 已知不可用 / 不稳定来源

| 来源 | 原因 |
|------|------|
| `douyinpic.com`（抖音） | ✅ **可以下载！** v8 新方案直接提取 `objurl` 下载，无需百度代理。`objurl` 指向 `miaobi-lite.cdn.bcebos.com`（百度 CDN 缓存），可直接访问。 |
| `sinaimg.cn`（新浪微博） | 需正确 Referer，直接curl被拦截 |
| `iknow-pic.cdn.bcebos.com`（百度百科） | 需百度 Referer，外部无法访问 |
| `gimg2.baidu.com`（百度搜索图） | 同上，需百度 Referer |
| `nimg.ws.126.net`（网易云音乐） | Referer限制，下载返回0字节 |
| `p3-tt.byteimg.com`（字节/头条） | 需今日头条/抖音 Referer |

### 注意事项

- **大量下载（>200张）**：用 `--keywords` 多关键词模式，自动切换关键词补充到目标数量
- **竖图用 `--ratio portrait`**：更容易找到 4K+ 内容
- **高质量用 `--z 7`**：百度优先返回近期高质量图片
- **JS 选择器必须用单引号**：`'a[href*=down]'`，双引号 `"a[href*=down]"` 会被 PowerShell 截断命令
- **百度链接会过期**：必须分批提取+立即下载，不要一次性提取所有链接后再下载

---

## 二、WALLHAVEN.CC（备选）

> 纯 API 调用，无需浏览器。竖版图片多，分辨率普遍 **3500x5250 ~ 4096x4096**

### API 调用

```
https://wallhaven.cc/api/v1/search?q=关键词&categories=111&purity=100&topRange=1M&page=1
```

| 参数 | 值 | 说明 |
|------|-----|------|
| q | 搜索词 | jk, school girl, portrait 等 |
| categories | 111 | 人物分类 |
| purity | 100 | 清除 NSFW |
| topRange | 1M | 最近一个月最热门 |
| page | 1 | 分页 |

### 搜索词推荐

```
jk, jk portrait, jk school, portrait photography, candid portrait
```

---

## 三、UNSPLASH（备选）

> 真实摄影风格为主，原图可达 **4000-9500px**

```bash
# 下载原图（关键：加 ?q=100&fm=jpg&raw=1）
curl -s -o output.jpg "https://images.unsplash.com/photo-xxx?q=100&fm=jpg&raw=1"
```

---

## 自动化使用规范

**配图优先级：百度图片搜索（主） → Wallhaven（备） → Unsplash（备）**

配图规范写作模板：

> 配图从百度图片搜索爬取高清图（详见本 skill），严禁AI生成图片。
>
> **百度图片（v8 重构版）**：
> - 单关键词：`python scripts/baidu_image_scraper_v8.py --keyword "关键词" --count 数量`
> - 多关键词：`python scripts/baidu_image_scraper_v8.py --keywords "词1" "词2" --count 数量 --output "目录"`
> - 竖图：加 `--ratio portrait --z 7`
> - 横图：加 `--ratio landscape --z 7`
> - 清理去重：`python scripts/baidu_image_scraper_v8.py --clean --output "目录"`
>
> **从已有链接文件下载**：`python scripts/baidu_image_scraper_v8.py --from-file links.json --output "目录" --count 数量`
>
> **百度不够时用 Wallhaven**：`wallhaven.cc/api/v1/search?q=关键词&categories=111&purity=100`
>
> **再不够用 Unsplash**：下载时加 `?q=100&fm=jpg&raw=1` 参数
>
> **禁止使用**：摄图网、知乎、image.so.com、Picsum 等平台
>
> **注意**：v8 直接从 `data-show-ext.objurl` 提取原图 URL，支持所有来源（含抖音）

### 各平台配图尺寸建议

| 平台 | 尺寸预设 | 说明 |
|------|---------|------|
| 公众号文章配图 | `4K_landscape`（3840×2160） | 16:9 横图 |
| 公众号贴图 | `4K_portrait`（2160×3840） | 9:16 竖图 |
| 小红书封面/竖图 | `4K_portrait` 或 `1080+_portrait` | 3:4 竖图最佳 |
| 小红书笔记配图 | `4K_square` 或 `1080+_square` | 1:1 方图 |
| 微博配图 | `4K_landscape` 或 `4K_square` | 横图或方图 |

---

## 常见问题

### Q1: 下载数量不足（比如要500张只下到300张）

**原因**：百度页面加载的图片数量有限，部分链接下载失败（403/超时）。

**解决**：
1. 用 `--keywords` 多关键词模式：`--keywords "JK少女" "JK制服 少女" "JK 高清美女"`
2. 增加 `--scroll` 参数，比如 `--scroll 25` 或 `--scroll 30`
3. 脚本已内置去重，重复运行不会下载相同图片

### Q2: 有很多重复图片

**原因**：同一图片可能在不同索引位置，或多次运行脚本导致。

**解决**：
1. 脚本已内置 MD5 哈希去重，下载时会自动跳过已存在的图片
2. 手动清理：`python scripts/baidu_image_scraper_unified.py --clean --output "目录"`
3. 清理模式会：删除小文件 + 哈希去重 + 重新编号

### Q3: 抖音图片下载失败

**原因**：旧方案中直接下载抖音原始 URL（`url=` 参数）会 403。

**解决**：v8 新方案直接提取 `data-show-ext.objurl`，该 URL 指向百度 CDN 缓存（`miaobi-lite.cdn.bcebos.com`），可直接下载。

### Q4: 脚本看起来"卡住不动"

**可能原因**：
1. 滚动阶段需要等待（每次 1.2 秒 × 滚动次数）
2. 大量链接下载中（每批 100 张，默认 8 线程）
3. 页面加载慢或出现验证码

**解决**：v7 已增加实时进度打印，可以看到每 20 张的下载进度。如果长时间无输出，可能是百度触发了验证码，需要手动关闭浏览器重试。

### Q5: 模型读不了图片，怎么挑图（2026-08-28 新增）

部分模型（如 hy4-dev）`Read` 图片会报 `does not support reading images`，没法肉眼挑图。
改用**标题元数据法**：抓 `data-show-ext` 里的 `title`，按标题挑，再定向下载。

**第 1 步：只抓标题，不下载**

```python
import json, importlib.util
spec = importlib.util.spec_from_file_location(
    "v8", "/Users/conycqzhang/.workbuddy/skills/image-scraper/scripts/baidu_image_scraper_v8.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
m.open_search_page("关键词", ratio='portrait', z=7)
m.scroll_and_load(10)
data = m.extract_all_data(500)   # 完整 data-show-ext，含 objurl + title
json.dump([{'objurl': d['objurl'], 'title': d.get('title', '')} for d in data],
          open('meta.json', 'w'), ensure_ascii=False)
```

**第 2 步：按标题挑候选，定向下载**（`objurl` 有短时效，抓完尽快下）

```bash
curl -sL -m 45 -o out.jpg -H "Referer: https://image.baidu.com/" \
  -H "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126 Safari/537.36" \
  "<objurl>"
```

下载后用 PIL 报 `width x height` + 文件大小，按「**标题对路 + 分辨率高 + 文件大**」定稿。

**标题挑图铁律**

| 标题特征 | 判断 | 处理 |
|---------|------|------|
| 含 解析 / 指南 / 参数 / 厂家 / 选购 / 多少钱 / PPT / 模板 / AE | 商品图 or 模板图 | **跳过** |
| 含 实拍 / 现场 / 日常 / 坚守 / XX里 / XX下 | 真实场景照 | **优先选** |

**关键词经验（实测）**

- **加「实拍」是分水岭**：`手术室 医生 手术 无影灯` → 270 条**全是**无影灯商品图 ❌；`外科医生 手术中 手术室 实拍` → 270 条真实手术室场景 ✅
- **关键词越长返回越少**：`数据中心 服务器 机房 科技感` 只返回 35 条（且大量 PPT 模板）；短关键词组合更稳
- 品牌/产品名直搜命中率高：`英伟达 显卡 GPU 芯片 科技` → 270 条芯片实拍，标题质量很高

**稳定性**

- 开跑前先 `pkill -f "Google Chrome Helper"` 清残留 Chrome（2026-08-27 曾因残留进程导致 v8 卡死 13 分钟 0 张图）
- **多个话题的爬图必须串行**，并行会让两个目录产出大量 MD5 重复的图

---

## 脚本清单

| 脚本 | 说明 | 状态 |
|------|------|------|
| `scripts/baidu_image_scraper_v8.py` | **v8 重构版** - 优先 objurl，失败用 url 兜底 | ✅ 唯一脚本 |

---

## 禁止使用

- ❌ 摄图网（分辨率低）
- ❌ 知乎图片（压缩严重）
- ❌ image.so.com（质量差）
- ❌ Picsum（随机图，不相关）
- ❌ AI 生成图片（任何平台）
