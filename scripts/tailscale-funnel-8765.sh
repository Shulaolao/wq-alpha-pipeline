#!/bin/bash
# Tailscale Funnel 8765 启动脚本
# 使用 --bg 后台模式，避免阻塞 launchd
# launchd 环境没有完整 PATH，需显式设置

export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin"

set -e

# 先重置所有旧 funnel 规则，防止 18789 等旧端口残留
echo "$(date): resetting existing funnel rules..."
/usr/local/bin/tailscale funnel reset 2>/dev/null || true
sleep 1

# 后台模式启动 funnel 8765
echo "$(date): starting funnel for port 8765 in background..."
/usr/local/bin/tailscale funnel --bg 127.0.0.1:8765

echo "$(date): funnel started successfully"