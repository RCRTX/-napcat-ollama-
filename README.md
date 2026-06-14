# QQ群聊监控系统 v1.0.0

一个基于 NapCat + Ollama 的QQ群聊监控、合规审查和告警通知系统。

## 功能特性

- **消息收集**: 通过NapCat WebSocket实时接收QQ群消息（文字/图片/表情包/语音/视频等）
- **数据存储**: 按群号+日期分文件存储，支持自动压缩归档和空间管理
- **AI合规审查**: 定时将聊天记录发送给本地Ollama（qwen2.5）进行深度合规审查
- **关键词过滤**: 支持自定义关键词和正则表达式，实时检测违规内容
- **告警通知**: 支持QQ私聊、邮件（QQ邮箱等）和微信推送（Server酱/PushPlus）
- **Web查询面板**: 浏览器访问，查看聊天记录、违规告警、统计数据
- **可分发**: 一键打包为zip，方便传播部署

## 系统要求

- Windows 10/11
- Python 3.8+
- NapCat (QQ机器人框架)
- Ollama (本地AI，可选)

## 快速开始

### 第一步：安装NapCat

1. 下载并安装 [NapCat](https://github.com/NapNeko/NapCatQQ)
2. 使用QQ扫码登录
3. 在NapCat配置中开启 WebSocket 服务（默认端口3001）
4. 确保NapCat的HTTP API也已开启（默认端口3000）

### 第二步：安装Ollama（AI审查）

1. 下载并安装 [Ollama](https://ollama.com/download)
2. 安装完成后打开终端，拉取模型：
   ```
   ollama pull qwen2.5
   ```
3. 验证运行：
   ```
   ollama list
   ```
   应该能看到 qwen2.5 模型

> 如果不需要AI审查，可以在配置文件中将 `ai_review.enabled` 设为 `false`，仅使用关键词过滤。

### 第三步：配置监控系统

1. 复制配置文件：
   ```
   copy config\config.example.json config\config.json
   ```

2. 编辑 `config\config.json`，修改以下关键配置：

   ```json
   {
       "napcat": {
           "ws_url": "ws://localhost:3001",
           "http_url": "http://localhost:3000",
           "monitor_groups": [123456789]  ← 改成你要监控的群号
       },
       "ai_review": {
           "enabled": true,
           "api_base": "http://localhost:11434/v1",
           "model": "qwen2.5"
       },
       "alert": {
           "qq": {
               "enabled": true,
               "recipient_user_ids": [123456789]  ← 改成接收告警的QQ号
           },
           "email": {
               "enabled": true,
               "smtp_host": "smtp.qq.com",
               "smtp_port": 465,
               "smtp_user": "你的QQ邮箱@qq.com",
               "smtp_password": "QQ邮箱授权码",  ← 不是QQ密码！
               "recipients": ["接收邮箱@qq.com"]
           },
           "push": {
               "enabled": true,
               "serverchan": {
                   "sendkey": "你的Server酱SendKey"
               }
           }
       }
   }
   ```

### 第四步：启动

双击 `start.bat` 即可启动。

启动后打开浏览器访问: **http://localhost:8080**

## 配置详解

### NapCat配置

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| ws_url | NapCat WebSocket地址 | ws://localhost:3001 |
| http_url | NapCat HTTP API地址 | http://localhost:3000 |
| token | 访问令牌（可选） | 空 |
| monitor_groups | 监控的群号列表 | 必填 |

### 存储配置

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| data_dir | 数据存储目录 | ./data |
| log_dir | 日志目录 | ./logs |
| export_dir | 人类可读聊天记录导出目录 | ./聊天记录 |
| max_storage_mb | 最大存储空间(MB) | 500 |
| archive_days | 归档天数 | 30 |
| file_rotate_hours | 文件轮转间隔(小时) | 24 |

### AI审查配置

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| enabled | 是否启用AI审查 | true |
| api_base | Ollama API地址 | http://localhost:11434/v1 |
| model | 模型名称 | qwen2.5 |
| review_interval_minutes | 审查间隔(分钟) | 5 |
| max_messages_per_review | 每次审查最大消息数 | 100 |

### 告警配置

**QQ私聊通知**:
- 需要NapCat HTTP API可用（默认 `http://localhost:3000`）
- 在 `alert.qq.recipient_user_ids` 填写接收告警的QQ号
- 接收方通常需要是机器人账号的好友，或允许接收该账号私聊

**邮件通知**:
- QQ邮箱需要开启SMTP服务并获取授权码（不是QQ密码）
- 授权码获取：QQ邮箱 → 设置 → 账户 → POP3/SMTP服务 → 开启 → 生成授权码

**微信推送**:
- Server酱: 在 [sct.ftqq.com](https://sct.ftqq.com/) 注册获取SendKey
- PushPlus: 在 [pushplus.plus](http://www.pushplus.plus/) 注册获取Token

### 关键词规则

编辑 `rules\keywords.txt`，每行一个关键词：
```
赌博
代开发票
刷单
/https?:\/\/.*\.cn\/[a-zA-Z0-9]+/   ← 正则表达式用//包裹
```

编辑 `rules\banned_words.txt`，每行一个严重违规词（命中直接高优先级告警）。

## Web面板功能

访问 http://localhost:8080 可以：

- **数据概览**: 查看监控群数、消息总数、告警数、存储使用等
- **聊天记录**: 按群组/关键词/用户/时间范围查询所有聊天记录
- **违规告警**: 查看所有违规记录，按级别筛选
- **群组管理**: 查看各群消息统计和可查日期

## 命令行参数

```
python src\main.py [选项]

选项:
  -c, --config      配置文件路径 (默认: config/config.json)
  --web-port        Web面板端口 (默认: 8080)
  --test-alert      发送测试告警
```

## 打包分发

运行打包脚本：
```
python build.py
```

会在 `dist` 目录下生成 `qq-monitor-v1.0.0-日期.zip`，解压即可使用。

## 项目结构

```
qq-monitor/
├── src/                    # 源代码
│   ├── __init__.py
│   ├── main.py            # 主程序入口
│   ├── config_loader.py   # 配置加载
│   ├── logger.py          # 日志模块
│   ├── napcat_client.py   # NapCat WebSocket客户端
│   ├── message_store.py   # 消息存储
│   ├── compliance.py       # AI合规审查
│   ├── alert_manager.py   # 告警通知
│   └── web_panel.py       # Web查询面板
├── config/                 # 配置文件
│   └── config.example.json
├── rules/                  # 规则文件
│   ├── keywords.txt
│   └── banned_words.txt
├── data/                   # 聊天记录数据（自动生成）
├── logs/                   # 日志文件（自动生成）
├── requirements.txt        # Python依赖
├── start.bat              # 启动脚本
├── test_alert.bat         # 测试告警脚本
├── build.py               # 打包脚本
└── README.md              # 本文件
```

## 常见问题

**Q: 启动报错"配置文件不存在"**
A: 需要先复制 config.example.json 为 config.json 并填写配置。

**Q: NapCat连接失败**
A: 确保NapCat已启动且WebSocket端口正确（默认3001）。

**Q: AI审查不工作**
A: 确保Ollama已安装并运行，qwen2.5模型已下载。可以在终端运行 `ollama serve` 启动服务。

**Q: 邮件发送失败**
A: 检查SMTP配置，QQ邮箱需要使用授权码而非密码。

**Q: 如何获取群号？**
A: 在NapCat中发送消息 `/get_group_info` 或在QQ中右键群 → 群信息查看。

## 免责声明

本工具仅供学习和内部管理使用。使用前请确保：
- 已告知群成员聊天内容会被监控
- 遵守相关法律法规和平台服务条款
- 不用于侵犯他人隐私或其他非法用途
