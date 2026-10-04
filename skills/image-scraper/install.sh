#!/bin/bash
#
# install.sh - 安装 image-scraper skill 到 WorkBuddy
#
# 用法:
#   ./install.sh              # 交互式安装
#   ./install.sh --force      # 强制覆盖
#

set -e

SKILL_NAME="image-scraper"
SKILL_SOURCE_DIR="$(cd "$(dirname "$0")" && pwd)"
WORKBUDDY_SKILLS_DIR="$HOME/.workbuddy/skills"
TARGET_DIR="$WORKBUDDY_SKILLS_DIR/$SKILL_NAME"
SCRIPTS_SOURCE="$SKILL_SOURCE_DIR/scripts"
SCRIPTS_TARGET="$HOME/WorkBuddy/AutoWork/scripts"

echo "image-scraper 安装脚本"
echo "=============================="
echo ""

# 检查 WorkBuddy 目录
if [ ! -d "$WORKBUDDY_SKILLS_DIR" ]; then
    echo "未找到 WorkBuddy skills 目录: $WORKBUDDY_SKILLS_DIR"
    echo "请先安装 WorkBuddy"
    exit 1
fi

# 检查 agent-browser
if ! command -v agent-browser &> /dev/null; then
    echo "未找到 agent-browser 命令"
    echo "请在 WorkBuddy 中启用 browser-automation 插件"
    echo "安装完成后可在 WorkBuddy 中使用本 skill"
    echo ""
fi

# 确认安装
if [ "$1" != "--force" ]; then
    if [ -d "$TARGET_DIR" ]; then
        echo "skill 已存在: $TARGET_DIR"
        echo "使用 --force 强制覆盖"
        exit 0
    fi
    echo "准备安装到: $TARGET_DIR"
    echo "脚本链接到: $SCRIPTS_TARGET"
    echo ""
fi

# 安装 skill
mkdir -p "$TARGET_DIR"
cp "$SKILL_SOURCE_DIR/SKILL.md" "$TARGET_DIR/"
echo "SKILL.md -> $TARGET_DIR/"

# 安装脚本（创建软链接，不复制）
if [ ! -d "$SCRIPTS_TARGET" ]; then
    mkdir -p "$(dirname "$SCRIPTS_TARGET")"
fi

if [ -f "$SCRIPTS_SOURCE/baidu_image_scraper.py" ]; then
    ln -sf "$SCRIPTS_SOURCE/baidu_image_scraper.py" "$SCRIPTS_TARGET/baidu_image_scraper.py"
    echo "脚本链接 -> $SCRIPTS_TARGET/baidu_image_scraper.py"
fi

if [ -f "$SCRIPTS_SOURCE/baidu_image_scraper_unified.py" ]; then
    ln -sf "$SCRIPTS_SOURCE/baidu_image_scraper_unified.py" "$SCRIPTS_TARGET/baidu_image_scraper_unified.py"
    echo "脚本链接 -> $SCRIPTS_TARGET/baidu_image_scraper_unified.py"
fi

if [ -f "$SCRIPTS_SOURCE/download_images.py" ]; then
    ln -sf "$SCRIPTS_SOURCE/download_images.py" "$SCRIPTS_TARGET/download_images.py"
    echo "脚本链接 -> $SCRIPTS_TARGET/download_images.py"
fi

echo ""
echo "=============================="
echo "安装完成！"
echo ""
echo "下一步："
echo "  1. 重启 WorkBuddy 使 skill 生效"
echo "  2. 运行测试："
echo "     python3 $SCRIPTS_TARGET/baidu_image_scraper_unified.py --keyword 'jk girl' --count 3 --ratio portrait"
