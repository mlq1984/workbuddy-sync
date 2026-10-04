# image-scraper · 高清图片爬虫

为内容创作者（公众号、小红书、博客等）爬取高质量配图的工具包。

---

## 特性

- **百度图片搜索为主**：图源最丰富，包含 B站/得物/大众点评/爱奇艺等高质量 CDN，竖图最高 4K+，横图最高 5K+
- **三源自动降级**：百度搜不到 → Wallhaven API → Unsplash，按需切换
- **竖图/横图分离**：支持 `portrait` / `landscape` / `both` 三种模式
- **分辨率自动过滤**：自动删除 800px 以下的低质量图
- **纯 Python 实现**：无需额外依赖，`curl` + `sips`（macOS 内置）

---

## 快速开始

### 前置要求

- **macOS**（使用了 `sips` 和 `agent-browser`）
- [WorkBuddy](https://www.codebuddy.cn) 安装并启用（提供 `agent-browser` 命令）
- Python 3.8+

### 安装

```bash
# 克隆或下载本仓库
git clone <repo-url> ~/my-skills/image-scraper
cd ~/my-skills/image-scraper
```

### 一键爬图

```bash
# 竖图 + 横图 各6张
python3 scripts/baidu_image_scraper.py "jk girl" 6 both

# 只爬竖图
python3 scripts/baidu_image_scraper.py "校园美女" 3 portrait

# 指定输出目录
python3 scripts/baidu_image_scraper.py "日系少女" 5 landscape ~/my-images/
```

运行后图片自动保存到 `./baidu-images/`（或你指定的目录），结构如下：

```
baidu-images/
├── jk girl_portrait/
│   ├── portrait_01.jpg   # 1920x2560  ✓
│   └── portrait_02.jpg   # 1440x1920  ✓
└── jk girl_landscape/
    ├── landscape_01.jpg  # 2560x1440  ✓
    └── landscape_02.jpg  # 1920x1440  ✓
```

---

## 工作原理

```
百度搜索页（JS渲染）
    ↓ agent-browser 打开 + 滚动加载
页面 HTML 中的 <img class="img_7rRSL" data-objurl="原始URL">
    ↓ JS 提取 data-objurl（注意：src 是 500px 缩略图，改参数无效）
objurl 直链（bdstatic / dpfile / hdslb / itc 等 CDN）
    ↓ curl 下载 + sips 检查分辨率
本地高清图片
```

---

## 图片来源说明

### 竖图（portrait）推荐

| 来源 | 说明 | 竖图分辨率 | 稳定性 |
|------|------|-----------|--------|
| `p1.meituan.net` | 美团CDN | **4480×6720** | 极高 |
| `q1/q8.itc.cn` | 爱奇艺CDN | **3000×4000** | 高 |
| `b0.bdstatic.com` | 百度CDN | 2000×2667 | 高 |
| `pic.rmb.bdstatic.com` | 贴吧/百科CDN | 1621×1080 | 高 |
| `image-cdn.poizon.com` | 得物CDN | 1920×1280 | 高 |
| `dpfile.com` | 大众点评CDN | 1920×1440 | 高 |
| `photo.tuchong.com` | 图虫摄影 | 1620×1080 | 中高 |

### 横图（landscape）推荐

| 来源 | 说明 | 横图分辨率 | 稳定性 |
|------|------|-----------|--------|
| `q4.itc.cn` | 爱奇艺CDN | **5307×4009** | 极高 |
| `cdn.sohucs.com` | 搜狐CDN | **3500×2214** | 高 |
| `b0.bdstatic.com` | 百度CDN | 2560×1440 | 高 |
| `hdslb.com` | B站CDN | 2560×1440 | 高 |
| `dpfile.com` | 大众点评CDN | **3070×2048** | 高 |
| `pic.rmb.bdstatic.com` | 贴吧/百科CDN | 1920×1280 | 高 |
| `gw.alicdn.com` | 阿里CDN | 1920×1920 | 中高 |

### 已知不稳定 / 不可用

| 来源 | 原因 |
|------|------|
| 抖音系（`douyinpic.com`） | ⚠️ 签名数小时内过期 |
| 新浪微博/博客（`sinaimg.cn`） | Referer 限制 |
| 百度百科（`iknow-pic.cdn.bcebos.com`） | Referer 限制 |
| 花瓣网（`gd-hbimg.huaban.com`） | Referer 限制 + 水印 |
| 京东（`img14.360buyimg.com`） | Referer 限制，质量差 |

---

## 图片质量说明

- 竖图（portrait，imgratio=2）最适合公众号封面和文章配图
- 横图（landscape，imgratio=4）适合小红书封面和Banner
- 建议优先选长边 **3000px+** 的图片

---

## 故障排除

### agent-browser 报 "not found"

确保 WorkBuddy 已安装并启用了 browser-automation 插件。

### objurl 全为空

1. 百度可能触发了反爬，等待几秒后重试
2. 增加等待时间：`agent-browser wait 3000`
3. 手动检查浏览器窗口是否正常加载了图片

### 下载的图片太小

可能是抖音等签名链接已过期。脚本会自动删除 50KB 以下的文件并重试，不达标则跳过。

---

## 第三方备选：Wallhaven / Unsplash

如百度方案不可用，可使用备选方案：

```bash
# Wallhaven - 纯 API
curl -s "https://wallhaven.cc/api/v1/search?q=jk&categories=111&purity=100&topRange=1M"

# Unsplash - 加 ?q=100&fm=jpg&raw=1 下载原图
curl -s -o output.jpg "https://images.unsplash.com/photo-xxx?q=100&fm=jpg&raw=1"
```

---

## License

MIT · 供个人/商业内容创作使用
