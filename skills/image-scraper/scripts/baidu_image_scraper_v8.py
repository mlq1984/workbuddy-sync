#!/usr/bin/env python3
"""
百度图片搜索爬虫 v8 (refactored)
================================
基于百度图片搜索新架构重构：
  - 旧方案: hover 触发下载链接生成 → 提取 a[href*=down]
  - 新方案: 直接提取 .img-cell-w6C5O 的 data-show-ext 属性中的 objurl

核心改进（v8）:
  1. 移除 hover 逻辑（百度不再生成 tn=download 链接）
  2. 直接从 data-show-ext 提取 objurl（原图 URL）
  3. 支持所有图源（抖音、B站、得物等）
  4. 更快更稳定，无需等待 hover 触发

使用方法:
  python baidu_image_scraper_v8.py --keyword "JK少女" --count 100
  python baidu_image_scraper_v8.py --keyword "JK少女" --count 200 --output "C:/output" --scroll 20
  python baidu_image_scraper_v8.py --keyword "JK少女" --count 100 --ratio portrait --z 7
  python baidu_image_scraper_v8.py --keywords "JK制服 少女" "JK 高清美女" --count 500 --output "C:/output"
  python baidu_image_scraper_v8.py --from-file links.json --output "output" --count 100
  python baidu_image_scraper_v8.py --clean --output "output"

前置要求:
  - agent-browser 命令可用（WorkBuddy 内置）
"""

import subprocess
import os
import sys
import json
import re
import time
import argparse
import hashlib
import threading
import urllib.request
import ssl
from pathlib import Path
from urllib.parse import urlparse, parse_qs, quote
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


# ── 配置 ────────────────────────────────────────────────
MAX_CONCURRENT = 8
MIN_FILE_SIZE = 10_000       # 最小 10KB（兜底过滤）
MIN_WIDTH = 800              # 最小宽度（px），低于此认为低质量
BUFFER_FACTOR = 1.2          # 目标 buffer：N × 1.2
DOWNLOAD_TIMEOUT = 30
SCROLL_PAUSE = 1.2
SCROLL_PIXELS = 1000
DEFAULT_SCROLL = 15          # 默认多滚动一些
BATCH_SIZE = 100             # 每批提取+下载数量
MAX_CONCURRENT_DIRS = 300    # 并发遍历目录的上限（防止卡顿）
IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp'}

# 部分图源证书链不完整（常见于CDN回源），关闭证书校验以提高抓取成功率
# 仅用于公开图片抓取，不涉及敏感数据传输
SSL_CONTEXT = ssl._create_unverified_context()


# ============================================================
# 原子文件名计数器（线程安全）
# ============================================================
class AtomicCounter:
    """线程安全的自增计数器，用于生成不冲突的文件名"""

    def __init__(self, start=0):
        self._value = start
        self._lock = threading.Lock()

    def next(self):
        with self._lock:
            val = self._value
            self._value += 1
            return val


# ============================================================
# shell 命令
# ============================================================
def run_cmd(cmd, timeout=60):
    """执行 shell 命令，返回 stdout（已清理 ANSI 和 CLIXML）"""
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        raw = r.stdout.strip()
        raw = re.sub(r'\x1b\[[0-9;]*m', '', raw)
        return raw, r.returncode
    except subprocess.TimeoutExpired:
        print(f"    [WARN] 命令超时 ({timeout}s): {cmd[:80]}...")
        return "", -1
    except Exception as e:
        print(f"    [WARN] 命令执行失败: {e}")
        return "", -1


# ============================================================
# 浏览器操作
# ============================================================
def build_search_url(keyword, ratio=None, z=None):
    """构建百度图片搜索 URL"""
    url = f"https://image.baidu.com/search/index?tn=baiduimage&fm=result&ie=utf-8&word={quote(keyword)}"
    if z:
        url += f"&z={z}"
    if ratio:
        ratio_map = {'portrait': '2', 'square': '3', 'landscape': '4'}
        url += f"&imgratio={ratio_map.get(ratio, ratio)}"
    return url


def maximize_browser():
    """最大化浏览器窗口"""
    run_cmd("agent-browser eval 'window.moveTo(0,0);window.resizeTo(screen.width,screen.height)'", timeout=10)


def open_search_page(keyword, ratio=None, z=None):
    """打开搜索页并最大化"""
    url = build_search_url(keyword, ratio=ratio, z=z)
    print(f"  打开页面...")
    run_cmd(f'agent-browser open "{url}"', timeout=60)
    print(f"  等待加载...")
    time.sleep(5)
    print(f"  最大化窗口...")
    maximize_browser()
    print(f"  页面已打开")
    return url


def scroll_and_load(times=DEFAULT_SCROLL):
    """滚动页面加载更多图片，带进度"""
    for i in range(times):
        print(f"  [DEBUG] 滚动 {i+1}/{times}...")
        run_cmd(f"agent-browser scroll down {SCROLL_PIXELS}", timeout=15)
        if (i + 1) % 5 == 0:
            print(f"    滚动 {i + 1}/{times}...")
        time.sleep(SCROLL_PAUSE)


# ============================================================
# 链接提取（新方案：从 data-show-ext 提取 objurl）
# ============================================================
def parse_eval_json(raw):
    """
    解析 agent-browser eval 返回的 JSON
    """
    try:
        raw = re.sub(r'\x1b\[[0-9;]*m', '', raw)
        raw = re.sub(r'#< CLIXML>.*?</Objs>', '', raw, flags=re.DOTALL)
        raw = re.sub(r'<Objs.*?</Objs>', '', raw, flags=re.DOTALL)
        raw = raw.strip()
        if not raw:
            return []
        # 处理外层引号（PowerShell 包裹）
        if raw.startswith('"') and raw.endswith('"'):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                raw = raw[1:-1]
        try:
            result = json.loads(raw)
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass
        # 最后尝试正则提取
        m = re.search(r'\[.*\]', raw, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                pass
    except Exception:
        pass
    return []


def extract_image_data(max_count=1500):
    """
    从 .img-cell-w6C5O 元素的 data-show-ext 属性中提取图片数据
    返回: list of dict, 每个包含 objurl 和 url（objurl 优先，失败时用 url 兜底）
    """
    print(f"  [DEBUG] extract_image_data: 从 data-show-ext 提取图片数据...")
    
    js_extract = (
        f"JSON.stringify(Array.from(document.querySelectorAll('.img-cell-w6C5O'))"
        f".map(function(cell){{"
        f"  try{{var ext=JSON.parse(cell.getAttribute('data-show-ext'));"
        f"    if(!ext)return null;"
        f"    return {{objurl:ext.objurl||'',url:ext.url||'',title:ext.title||''}};}}"
        f"  catch(e){{return null;}}"
        f"}}).filter(function(d){{return d!==null&&(d.objurl||d.url);}}).slice(0,{max_count}))"
    )
    
    out, _ = run_cmd(f'agent-browser eval "{js_extract}"', timeout=30)
    print(f"  [DEBUG] extract_image_data: 获取到原始输出 {len(out)} 字符")
    
    data = parse_eval_json(out)
    return dedup_image_data(data) if data else []


def dedup_image_data(data_list):
    """按 url 去重"""
    seen = set()
    unique = []
    for item in data_list:
        url = item.get('url', '') or item.get('objurl', '')
        if url and url not in seen:
            seen.add(url)
            unique.append(item)
    return unique


def dedup_objurls(objurls):
    """按 URL 去重"""
    seen = set()
    unique = []
    for url in objurls:
        if url and url not in seen:
            seen.add(url)
            unique.append(url)
    return unique


def extract_all_data(max_count=1500):
    """
    提取完整的 data-show-ext 数据（包含 objurl, title, cs, setsign 等）
    返回: list of dict
    """
    print(f"  [DEBUG] extract_all_data: 提取完整数据...")
    
    js_extract = (
        f"JSON.stringify(Array.from(document.querySelectorAll('.img-cell-w6C5O'))"
        f".map(function(cell){{"
        f"  try{{return JSON.parse(cell.getAttribute('data-show-ext'));}}"
        f"  catch(e){{return null;}}"
        f"}}).filter(function(d){{return d!==null&&d.objurl;}}).slice(0,{max_count}))"
    )
    
    out, _ = run_cmd(f'agent-browser eval "{js_extract}"', timeout=30)
    data = parse_eval_json(out)
    return data if data else []


def load_links_from_file(filepath):
    """从文件加载链接（自动处理各种编码）"""
    content = None
    for enc in ['utf-16', 'utf-8-sig', 'utf-8', 'latin-1']:
        try:
            with open(filepath, 'r', encoding=enc) as f:
                content = f.read()
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
    if not content:
        return []
    # 清理 ANSI 和 CLIXML 噪音
    content = re.sub(r'\x1b\[[0-9;]*m', '', content)
    content = re.sub(r'#< CLIXML>.*?</Objs>', '', content, flags=re.DOTALL)
    content = re.sub(r'<Objs.*?</Objs>', '', content, flags=re.DOTALL)
    content = content.strip()
    if not content:
        return []
    # 如果是 JSON 文件（内容开头是 [）
    if content.startswith('['):
        return parse_eval_json(content)
    # 否则尝试按行解析
    return [line.strip() for line in content.splitlines() if line.strip() and line.strip().startswith('http')]


# ============================================================
# 文件操作
# ============================================================
def get_existing_hashes(output_dir):
    """获取目录中已有文件的 MD5 哈希集合（限制并发遍历）"""
    hashes = set()
    dir_path = Path(output_dir)
    if not dir_path.exists():
        return hashes
    files = [f for f in dir_path.iterdir() if f.is_file() and f.suffix.lower() in IMAGE_EXTS]
    for f in files[:MAX_CONCURRENT_DIRS]:
        try:
            h = hashlib.md5()
            with open(f, 'rb') as fp:
                while True:
                    chunk = fp.read(8192)
                    if not chunk:
                        break
                    h.update(chunk)
            hashes.add(h.hexdigest())
        except Exception:
            pass
    return hashes


def count_valid_images(output_dir):
    """统计有效图片数量和总大小"""
    dir_path = Path(output_dir)
    if not dir_path.exists():
        return 0, 0
    count = 0
    total_size = 0
    for f in dir_path.iterdir():
        if f.is_file() and f.suffix.lower() in IMAGE_EXTS:
            try:
                sz = f.stat().st_size
                if sz >= MIN_FILE_SIZE:
                    count += 1
                    total_size += sz
            except OSError:
                pass
    return count, total_size


def get_next_index(output_dir):
    """获取下一个可用的文件索引（从目录中找最大编号+1）"""
    dir_path = Path(output_dir)
    if not dir_path.exists():
        return 0
    max_idx = -1
    for f in dir_path.iterdir():
        if f.is_file() and f.stem.startswith('img_'):
            try:
                idx = int(f.stem[4:])
                if idx > max_idx:
                    max_idx = idx
            except ValueError:
                pass
    return max_idx + 1 if max_idx >= 0 else 0


def guess_ext_from_url(url):
    """从 URL 推测文件扩展名"""
    if not url:
        return '.jpg'
    
    url_lower = url.lower()
    
    # 抖音/字节
    if 'douyinpic.com' in url_lower or 'bytedance' in url_lower:
        return '.jpg'
    
    # 从 URL 路径推测
    for ext in ['.jpeg', '.jpg', '.png', '.webp', '.gif', '.bmp']:
        if ext in url_lower:
            return ext if ext != '.jpeg' else '.jpg'
    
    return '.jpg'


# ============================================================
# 下载逻辑（线程安全）
# ============================================================
def download_single(image_data, output_dir, counter, existing_hashes, lock):
    """
    下载单张图片（线程安全版本）
    优先使用 objurl，失败时使用 url 兜底
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'https://image.baidu.com',
    }
    
    # 获取 URLs（优先 objurl，失败时用 url 兜底）
    objurl = image_data.get('objurl', '') if isinstance(image_data, dict) else ''
    url = image_data.get('url', '') if isinstance(image_data, dict) else str(image_data)
    
    urls_to_try = []
    if objurl:
        urls_to_try.append(objurl)
    if url and url != objurl:
        urls_to_try.append(url)
    
    if not urls_to_try:
        return 'fail', 0, 'no_url'
    
    last_error = ''
    for try_url in urls_to_try:
        try:
            req = urllib.request.Request(try_url, headers=headers)
            with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT, context=SSL_CONTEXT) as resp:
                data = resp.read()

            if len(data) < MIN_FILE_SIZE:
                last_error = 'too_small'
                continue

            h = hashlib.md5(data).hexdigest()

            # 哈希去重检查（加锁）
            with lock:
                if h in existing_hashes:
                    return 'dup', 0, 'hash_dup'
                existing_hashes.add(h)

            # 生成文件名（原子计数器，不冲突）
            idx = counter.next()
            ext = guess_ext_from_url(try_url)
            fpath = str(Path(output_dir) / f'img_{idx}{ext}')

            with open(fpath, 'wb') as f:
                f.write(data)

            return 'ok', len(data), fpath
        except Exception as e:
            last_error = str(e)[:60]
            continue
    
    return 'fail', 0, last_error


def download_batch(image_data_list, output_dir, counter, existing_hashes, lock):
    """并发下载一批图片数据"""
    results = {'ok': 0, 'fail': 0, 'dup': 0, 'size': 0}
    total = len(image_data_list)

    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT) as exe:
        futures = {
            exe.submit(download_single, data, output_dir, counter, existing_hashes, lock): i
            for i, data in enumerate(image_data_list)
        }
        done_count = 0
        for future in as_completed(futures):
            done_count += 1
            status, size, info = future.result()
            results[status] += 1
            if status == 'ok':
                results['size'] += size
            if done_count % 20 == 0 or done_count == total:
                print(f"    进度: {done_count}/{total} (ok={results['ok']}, dup={results['dup']}, fail={results['fail']})")

    return results


# ============================================================
# 下载后清理：去重 + 删低质量
# ============================================================
def cleanup_output(output_dir):
    """
    下载完毕后做清理：
    1. MD5 去重（保留最大文件）
    2. 删除宽/高 < MIN_WIDTH 的低质量图
    3. 重命名编号
    """
    output_dir = Path(output_dir)
    if not output_dir.exists():
        return 0, 0

    # 1. MD5 去重
    file_hashes = {}
    for f in output_dir.iterdir():
        if not (f.is_file() and f.suffix.lower() in IMAGE_EXTS):
            continue
        try:
            h = hashlib.md5()
            with open(f, 'rb') as fp:
                while True:
                    chunk = fp.read(8192)
                    if not chunk:
                        break
                    h.update(chunk)
            digest = h.hexdigest()
            file_hashes.setdefault(digest, []).append(f)
        except Exception:
            pass

    dup_count = 0
    for h, files in file_hashes.items():
        if len(files) > 1:
            files.sort(key=lambda f: f.stat().st_size, reverse=True)
            for f in files[1:]:
                f.unlink()
                dup_count += 1

    # 2. 删除低质量图（宽或高 < MIN_WIDTH）
    lowq_count = 0
    lowq_size = 0
    if HAS_PIL:
        for f in output_dir.iterdir():
            if not (f.is_file() and f.suffix.lower() in IMAGE_EXTS):
                continue
            try:
                with Image.open(f) as img:
                    w, h_img = img.size
                    if w < MIN_WIDTH and h_img < MIN_WIDTH:
                        lowq_size += f.stat().st_size
                        f.unlink()
                        lowq_count += 1
            except Exception:
                try:
                    lowq_size += f.stat().st_size
                    f.unlink()
                    lowq_count += 1
                except OSError:
                    pass
    else:
        # 没有 PIL，用文件大小兜底：< 30KB 认为低质量
        for f in output_dir.iterdir():
            if not (f.is_file() and f.suffix.lower() in IMAGE_EXTS):
                continue
            try:
                if f.stat().st_size < 30_000:
                    lowq_size += f.stat().st_size
                    f.unlink()
                    lowq_count += 1
            except OSError:
                pass

    # 3. 重命名编号（填补空缺）
    all_files = sorted([
        f for f in output_dir.iterdir()
        if f.is_file() and f.suffix.lower() in IMAGE_EXTS
    ])
    for i, f in enumerate(all_files):
        new_name = f"img_{i}{f.suffix.lower()}"
        if f.name != new_name:
            new_path = output_dir / new_name
            if new_path.exists() and new_path != f:
                tmp = output_dir / f"_tmp_renaming_{i}{f.suffix}"
                if tmp.exists():
                    tmp.unlink()
                new_path.rename(tmp)
            if not new_path.exists():
                f.rename(new_path)
            else:
                f.unlink()

    final_count, final_size = count_valid_images(output_dir)
    print(f"\n  [清理完成]")
    print(f"    去重删除: {dup_count} 个")
    print(f"    低质量删除: {lowq_count} 个 ({lowq_size // 1024}KB)")
    print(f"    最终: {final_count} 张, {final_size // 1024 // 1024}MB")
    return final_count, final_size


# ============================================================
# 单关键词爬取流程（v8 新方案）
# ============================================================
def scrape_keyword(keyword, output_dir, counter, existing_hashes, lock,
                   need=100, scroll_times=DEFAULT_SCROLL, ratio=None, z=None):
    """爬取一个关键词，返回新增数量。自动多轮滚动直到满足需求或无更多链接。"""
    if need <= 0:
        return 0

    print(f"\n{'='*60}")
    print(f"[关键词] {keyword}")
    print(f"  还需: {need} 张")

    # 打开搜索页
    open_search_page(keyword, ratio=ratio, z=z)

    total_new = 0
    round_num = 0
    max_rounds = 5  # 最多 5 轮滚动

    while total_new < need and round_num < max_rounds:
        round_num += 1
        print(f"\n  --- 第 {round_num} 轮 ---")

        if round_num > 1:
            # 后续轮次继续滚动
            extra_scroll = min(scroll_times, 10)
            print(f"  继续滚动 ({extra_scroll} 次)...")
            scroll_and_load(extra_scroll)
        else:
            # 第一轮正常滚动
            print(f"  滚动加载 ({scroll_times} 次)...")
            scroll_and_load(scroll_times)

        # v8: 提取图片数据（包含 objurl 和 url）
        print(f"  提取图片数据...")
        image_data_list = extract_image_data(max_count=1500)
        
        if not image_data_list:
            print(f"  -> 本轮未提取到数据，结束")
            break

        print(f"  提取到 {len(image_data_list)} 个去重图片数据")

        # 计算本轮还需要多少
        remaining = need - total_new

        # 分批下载
        batch_num = 0
        batch_data = [image_data_list[i:i + BATCH_SIZE] for i in range(0, len(image_data_list), BATCH_SIZE)]

        for batch_data_chunk in batch_data:
            if total_new >= need:
                break
            batch_num += 1
            batch_remaining = need - total_new
            to_download = batch_data_chunk[:batch_remaining]

            print(f"  -> 下载批次 {batch_num}: {len(to_download)} 张...")
            results = download_batch(to_download, output_dir, counter, existing_hashes, lock)
            batch_new = results['ok']
            total_new += batch_new

            print(f"     批次结果: {batch_new} 新增, {results['dup']} 重复, {results['fail']} 失败")
            print(f"     累计新增: {total_new}/{need}")

            time.sleep(0.5)

        if len(image_data_list) < 20:
            print(f"  -> 数据不足 20 个，可能已到底部")
            break

    print(f"  [{keyword}] 共新增 {total_new} 张 ({round_num} 轮)")
    return total_new


# ============================================================
# 已知问题（2026-04-24）：百度图片搜索结果存在严重的泛化问题
# 当主关键词图片不足时，会自动切换到 _SUPPLEMENT_KEYWORDS（默认全是JK）
# 这导致科技类关键词搜索会混入大量不相关的JK图片
#
# 修复建议：
# 1. 根据主关键词类别选择同类别补充词（科技→科技，美食→美食）
# 2. 或者移除自动切换逻辑，只用主关键词
# 3. 或者提示用户确认是否需要补充
# ============================================================


# ============================================================
# 主流程：单关键词模式
# ============================================================
_SUPPLEMENT_KEYWORDS = [
    "JK制服 少女",
    "JK美女 高清",
    "日本JK制服",
    "校園美女 写真",
    "JK裙 少女",
]

def run_single_keyword(keyword, count, output_dir, scroll_times, ratio=None, z=None):
    """
    单关键词爬取模式：
    1. 目标 = N × 1.2（内部 buffer，不严格追数）
    2. 主词不够 → 自动切换备用关键词
    3. 全部下载完后 → 自动去重 + 删低质量
    """
    output_dir = Path(output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    target = int(count * BUFFER_FACTOR)

    print(f"\n[百度图片爬虫 v8 - 单关键词模式]")
    print(f"  关键词: {keyword}")
    print(f"  用户目标: {count} 张（内部目标: {target} 张，含20%buffer）")
    print(f"  输出: {output_dir}")
    if ratio:
        print(f"  方向: {ratio}")
    if z:
        print(f"  质量: z={z}")
    print(f"  滚动: {scroll_times} 次")
    print("=" * 60)

    existing_count, existing_size = count_valid_images(output_dir)
    need = target - existing_count
    print(f"\n  已有: {existing_count} 张 ({existing_size // 1024 // 1024}MB)")
    print(f"  目标: {target} 张（{count}+20%buffer）")

    if need <= 0:
        print(f"\n  已有足够图片，跳过下载")
        cleanup_output(output_dir)
        return existing_count

    counter = AtomicCounter(start=get_next_index(output_dir))
    existing_hashes = get_existing_hashes(output_dir)
    lock = threading.Lock()

    # ⚠️ 临时禁用补充关键词（2026-04-24：默认只用主关键词，避免JK等问题）
    # 如果需要补充关键词，请在命令行使用 --keywords 参数手动指定
    # all_keywords = [keyword] + _SUPPLEMENT_KEYWORDS
    all_keywords = [keyword]
    used_keywords = []

    total_new = 0
    for kw in all_keywords:
        if total_new >= need:
            break
        kw_need = need - total_new
        print(f"\n  [还差 {kw_need} 张] <- 切换到: {kw}")
        kw_new = scrape_keyword(kw, str(output_dir), counter, existing_hashes, lock,
                                need=kw_need, scroll_times=scroll_times, ratio=ratio, z=z)
        total_new += kw_new
        used_keywords.append(kw)
        if kw_new > 0:
            print(f"  [{kw}] 新增 {kw_new} 张，累计 {total_new}/{need}")

    print(f"\n{'='*60}")
    print(f"下载完成，共新增 {total_new} 张")
    print(f"开始清理（去重 + 删低质量）...")
    final_count, final_size = cleanup_output(output_dir)

    print(f"\n{'='*60}")
    print(f"完成! 目录共 {final_count} 张 ({final_size // 1024 // 1024}MB)")
    print(f"  （目标 {count} 张，清理后 {final_count} 张）")
    return final_count


# ============================================================
# 主流程：多关键词补充模式
# ============================================================
def run_multi_keywords(keywords, count, output_dir, scroll_times, ratio=None, z=None):
    """多关键词补充模式"""
    output_dir = Path(output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n[百度图片爬虫 v8 - 多关键词模式]")
    print(f"  关键词: {', '.join(keywords)}")
    print(f"  目标: {count} 张")
    print(f"  输出: {output_dir}")
    print("=" * 60)

    existing_count, existing_size = count_valid_images(output_dir)
    need = count - existing_count
    print(f"\n  已有: {existing_count} 张 ({existing_size // 1024 // 1024}MB)")
    print(f"  还需: {need} 张")

    if need <= 0:
        print(f"\n  已有 {existing_count} 张，无需下载")
        return existing_count

    counter = AtomicCounter(start=get_next_index(output_dir))
    existing_hashes = get_existing_hashes(output_dir)
    lock = threading.Lock()

    total_new = 0
    for kw in keywords:
        if total_new >= need:
            break
        kw_new = scrape_keyword(kw, str(output_dir), counter, existing_hashes, lock,
                                need=need - total_new, scroll_times=scroll_times,
                                ratio=ratio, z=z)
        total_new += kw_new

    final_count, final_size = count_valid_images(output_dir)
    print(f"\n{'='*60}")
    print(f"完成! 新增 {total_new} 张, 目录共 {final_count} 张, {final_size // 1024 // 1024}MB")
    return final_count


# ============================================================
# 主流程：从文件下载模式
# ============================================================
def run_from_file(links_file, output_dir, count):
    """从已有链接文件下载"""
    output_dir = Path(output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n[百度图片爬虫 v8 - 文件下载模式]")
    print(f"  链接文件: {links_file}")
    print(f"  输出: {output_dir}")
    print(f"  目标: {count} 张")
    print("=" * 60)

    urls = load_links_from_file(links_file)
    print(f"  加载链接: {len(urls)} 个")
    urls = dedup_objurls(urls)
    print(f"  去重后: {len(urls)} 个")
    urls = urls[:count]
    
    # 转换为图片数据格式（只有 url，没有 objurl）
    image_data_list = [{'url': url, 'objurl': ''} for url in urls]

    counter = AtomicCounter(start=get_next_index(output_dir))
    existing_hashes = get_existing_hashes(output_dir)
    lock = threading.Lock()

    results = download_batch(image_data_list, str(output_dir), counter, existing_hashes, lock)

    final_count, final_size = count_valid_images(output_dir)
    print(f"\n{'='*60}")
    print(f"完成! {results['ok']} 成功, {results['dup']} 重复, {results['fail']} 失败")
    print(f"目录共 {final_count} 张, {final_size // 1024 // 1024}MB")
    return final_count


# ============================================================
# 清理模式
# ============================================================
def run_clean(output_dir):
    """清理小文件和哈希去重"""
    output_dir = Path(output_dir).expanduser().resolve()
    if not output_dir.exists():
        print(f"目录不存在: {output_dir}")
        return

    print(f"\n[清理模式]")
    print(f"  目录: {output_dir}")

    # 1. 删除小文件
    small_count = 0
    small_size = 0
    for f in output_dir.iterdir():
        if f.is_file() and f.suffix.lower() in IMAGE_EXTS:
            try:
                sz = f.stat().st_size
                if sz < MIN_FILE_SIZE:
                    small_size += sz
                    f.unlink()
                    small_count += 1
            except OSError:
                pass

    # 2. 哈希去重
    file_hashes = {}
    for f in output_dir.iterdir():
        if f.is_file() and f.suffix.lower() in IMAGE_EXTS:
            try:
                h = hashlib.md5()
                with open(f, 'rb') as fp:
                    while True:
                        chunk = fp.read(8192)
                        if not chunk:
                            break
                        h.update(chunk)
                digest = h.hexdigest()
                if digest not in file_hashes:
                    file_hashes[digest] = []
                file_hashes[digest].append(f)
            except Exception:
                pass

    dup_count = 0
    for h, files in file_hashes.items():
        if len(files) > 1:
            files.sort(key=lambda f: f.stat().st_size, reverse=True)
            for f in files[1:]:
                f.unlink()
                dup_count += 1

    # 3. 重命名文件
    all_files = sorted([f for f in output_dir.iterdir() if f.is_file() and f.suffix.lower() in IMAGE_EXTS])
    for i, f in enumerate(all_files):
        new_name = f"img_{i}{f.suffix.lower()}"
        if f.name != new_name:
            new_path = output_dir / new_name
            if new_path.exists() and new_path != f:
                tmp_path = output_dir / f"_tmp_renaming_{i}{new_path.suffix}"
                if tmp_path.exists():
                    tmp_path.unlink()
                new_path.rename(tmp_path)
            if not new_path.exists():
                f.rename(new_path)
            else:
                f.unlink()

    final_count, final_size = count_valid_images(output_dir)
    print(f"\n  删除小文件: {small_count} 个 ({small_size // 1024}KB)")
    print(f"  去重删除: {dup_count} 个")
    print(f"  最终: {final_count} 张, {final_size // 1024 // 1024}MB")


# ============================================================
# CLI 入口
# ============================================================
def main():
    parser = argparse.ArgumentParser(
        description="百度图片搜索爬虫 v8（重构版 - 直接从 data-show-ext 提取 objurl）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # 单关键词爬取 100 张
  python baidu_image_scraper_v8.py --keyword "JK少女" --count 100

  # 单关键词 + 自定义输出目录 + 高质量
  python baidu_image_scraper_v8.py --keyword "JK少女" --count 200 --output "C:/photos" --z 7 --scroll 20

  # 多关键词补充到 500 张
  python baidu_image_scraper_v8.py --keywords "JK制服 少女" "JK 高清美女" "日本JK制服" --count 500

  # 从已有链接文件下载
  python baidu_image_scraper_v8.py --from-file links.json --output "output" --count 100

  # 清理小文件 + 去重
  python baidu_image_scraper_v8.py --clean --output "output"

技术原理（v8 新方案）:
  1. agent-browser 打开搜索页 + 滚动加载
  2. 直接从 .img-cell-w6C5O 的 data-show-ext 属性提取 objurl（原图URL）
  3. 无需 hover 触发，更快更稳定
  4. 支持所有图源（抖音、B站、得物等）
  5. 线程安全原子计数器 + MD5 哈希去重
        """
    )

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--keyword", metavar="KW", help="单关键词爬取模式")
    mode.add_argument("--keywords", nargs='+', metavar="KW", help="多关键词补充模式")
    mode.add_argument("--from-file", metavar="FILE", help="从已有链接文件下载")
    mode.add_argument("--clean", action="store_true", help="清理小文件和去重")

    parser.add_argument("--count", type=int, default=50, help="下载数量，默认50")
    parser.add_argument("--output", default="./image-scraper-downloads/", help="输出目录")
    parser.add_argument("--scroll", type=int, default=DEFAULT_SCROLL, metavar="N",
                        help=f"滚动次数，默认{DEFAULT_SCROLL}")
    parser.add_argument("--ratio", choices=["portrait", "square", "landscape"],
                        help="图片方向：portrait(竖图) square(方图) landscape(横图)")
    parser.add_argument("--z", type=int, choices=[3, 5, 6, 7, 9],
                        help="图片质量参数（7=近期高质量）")

    args = parser.parse_args()

    if args.clean:
        run_clean(args.output)
    elif args.keyword:
        run_single_keyword(args.keyword.strip(), args.count, args.output, args.scroll,
                           ratio=args.ratio, z=args.z)
    elif args.keywords:
        run_multi_keywords(args.keywords, args.count, args.output, args.scroll,
                           ratio=args.ratio, z=args.z)
    elif args.from_file:
        run_from_file(args.from_file, args.output, args.count)


if __name__ == "__main__":
    main()
