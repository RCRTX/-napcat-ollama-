@echo off
chcp 65001 >nul
title QQ群聊监控系统 - 测试告警

echo 发送测试告警...
python src\main.py -c config\config.json --test-alert
pause
