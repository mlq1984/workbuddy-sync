#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
后台自动重试脚本：监控 Agnes 视频队列，恢复时自动生成真 AI 动态视频
"""

import sys
import time
import json
import base64
import requests
from pathlib import Path
from datetime import datetime

# 配置
API_KEY = 'sk-nNWR2IFP4dZnc3qFmvneQXMkWuu8yEmUQ5Uldf1UPiz4MNCD'
BASE_URL = 'https://apihub.agnes-ai.com/v1'
HEADERS = {'Authorization': f'Bearer {API_KEY}', 'Content-Type': 'application/json'}

# 源图片
IMG_PATH = Path(__file__).parent.parent / 'poster_output' / 'image_1795586098.jpg'
OUT_PATH = Path(__file__).parent.parent / 'poster_output' / 'video_dog_walk_ai_real.mp4'

# 视频参数
VIDEO_PARAMS = {
    'model': 'agnes-video-2.5-flash',
    'prompt': 'The woman and golden retriever dog walking naturally in the park, dog running happily beside her, legs moving naturally, fur flowing in breeze, realistic physics, natural camera follow, cinematic lighting, photorealistic',
    'mode': 'reference',
    'seconds': '5',
    'size': '720P',
    'aspect_ratio': '9:16',
}

# 重试配置
RETRY_INTERVAL = 60  # 每 60 秒检查一次
MAX_RETRIES = 240    # 最多重试 240 次 (24 小时)
LOG_FILE = Path(__file__).parent.parent / 'poster_output' / 'video_retry_log.txt'


def log(msg: str):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f'[{timestamp}] {msg}'
    print(line)
    LOG_FILE.parent.mkdir(exist_ok=True)
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(line + '\n')


def create_task(payload: dict) -> dict:
    """创建视频任务，返回 {success, video_id, task_id, error}"""
    try:
        resp = requests.post(f'{BASE_URL}/videos', headers=HEADERS, json=payload, timeout=180)
        if resp.status_code == 200:
            data = resp.json()
            video_id = data.get('video_id') or data.get('id')
            task_id = data.get('task_id')
            return {'success': True, 'video_id': video_id, 'task_id': task_id, 'raw': data}
        elif resp.status_code == 503:
            return {'success': False, 'error': 'queue_full', 'raw': resp.json()}
        else:
            return {'success': False, 'error': f'http_{resp.status_code}', 'raw': resp.text}
    except Exception as e:
        return {'success': False, 'error': f'exception_{type(e).__name__}', 'raw': str(e)}


def poll_result(video_id: str, model_name: str = 'agnes-video-2.5-flash') -> dict:
    """轮询视频结果"""
    poll_url = 'https://apihub.agnes-ai.com/agnesapi'
    for _ in range(120):  # 最多轮询 120 次 (6 分钟)
        time.sleep(3)
        try:
            resp = requests.get(poll_url, headers=HEADERS, params={'video_id': video_id, 'model_name': model_name}, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                status = data.get('status') or data.get('data', {}).get('status')
                if status == 'completed':
                    video_url = (data.get('metadata', {}).get('url') or 
                                data.get('data', {}).get('metadata', {}).get('url') or 
                                data.get('video_url'))
                    return {'success': True, 'video_url': video_url, 'raw': data}
                elif status == 'failed':
                    return {'success': False, 'error': 'generation_failed', 'raw': data}
        except Exception as e:
            log(f'轮询异常: {e}')
    return {'success': False, 'error': 'poll_timeout'}


def download_video(video_url: str, out_path: Path) -> bool:
    """下载视频文件"""
    try:
        resp = requests.get(video_url, timeout=180)
        if resp.status_code == 200:
            out_path.write_bytes(resp.content)
            size_mb = len(resp.content) / 1024 / 1024
            log(f'✅ 视频下载完成: {out_path} ({size_mb:.1f} MB)')
            return True
        else:
            log(f'❌ 下载失败: HTTP {resp.status_code}')
            return False
    except Exception as e:
        log(f'❌ 下载异常: {e}')
        return False


def prepare_payload() -> dict:
    """准备包含图片的 payload"""
    img_bytes = IMG_PATH.read_bytes()
    b64 = base64.b64encode(img_bytes).decode()
    data_uri = f'data:image/jpeg;base64,{b64}'
    
    payload = VIDEO_PARAMS.copy()
    payload['images'] = [data_uri]
    return payload


def main():
    log('=' * 60)
    log('🚀 启动后台视频生成监控任务')
    log(f'源图片: {IMG_PATH}')
    log(f'输出路径: {OUT_PATH}')
    log(f'检查间隔: {RETRY_INTERVAL}秒')
    log(f'最大重试: {MAX_RETRIES}次')
    log('=' * 60)
    
    # 准备 payload
    payload = prepare_payload()
    
    for attempt in range(1, MAX_RETRIES + 1):
        log(f'--- 第 {attempt}/{MAX_RETRIES} 次尝试 ---')
        
        # 1. 创建任务
        result = create_task(payload)
        
        if not result['success']:
            if result['error'] == 'queue_full':
                log(f'⏳ 队列仍满 (503)，{RETRY_INTERVAL}秒后重试...')
                time.sleep(RETRY_INTERVAL)
                continue
            else:
                log(f'❌ 创建任务失败: {result["error"]} - {result.get("raw", "")}')
                time.sleep(RETRY_INTERVAL)
                continue
        
        video_id = result['video_id']
        task_id = result['task_id']
        log(f'✅ 任务创建成功: video_id={video_id}, task_id={task_id}')
        
        # 2. 轮询结果
        log('🔄 开始轮询视频生成进度...')
        poll_result_data = poll_result(video_id)
        
        if not poll_result_data['success']:
            log(f'❌ 轮询失败: {poll_result_data["error"]}')
            time.sleep(RETRY_INTERVAL)
            continue
        
        video_url = poll_result_data['video_url']
        log(f'🎬 视频生成完成，开始下载: {video_url}')
        
        # 3. 下载视频
        if download_video(video_url, OUT_PATH):
            log('🎉 真 AI 动态视频生成成功！任务结束。')
            log(f'📁 最终文件: {OUT_PATH}')
            
            # 成功后可以发送通知（企业微信等）
            # 这里只记录日志
            return 0
        else:
            log('❌ 下载失败，继续重试...')
            time.sleep(RETRY_INTERVAL)
    
    log('⏰ 达到最大重试次数，任务结束')
    return 1


if __name__ == '__main__':
    sys.exit(main())