"""
Web查询面板
提供浏览器端的聊天记录查询、告警查看、统计概览等功能
"""

import os
import json
import shutil
from datetime import datetime
from typing import Dict, Any, Optional

from flask import Flask, jsonify, request, render_template_string, send_from_directory
from flask_cors import CORS

from .message_store import MessageStore
from .logger import setup_logger

logger = setup_logger("web_panel")


# ==================== HTML模板 ====================

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>QQ群聊监控系统</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: 'Microsoft YaHei', -apple-system, sans-serif; background: #f0f2f5; color: #333; }
.header { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px 30px; display: flex; justify-content: space-between; align-items: center; box-shadow: 0 2px 10px rgba(0,0,0,.2); }
.header h1 { font-size: 22px; font-weight: 600; }
.header .status { display: flex; gap: 15px; align-items: center; font-size: 14px; }
.status-dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; margin-right: 5px; }
.status-dot.online { background: #52c41a; box-shadow: 0 0 6px #52c41a; }
.status-dot.offline { background: #ff4d4f; }
.container { max-width: 1400px; margin: 20px auto; padding: 0 20px; }
.tabs { display: flex; gap: 5px; margin-bottom: 20px; background: white; padding: 8px; border-radius: 10px; box-shadow: 0 1px 4px rgba(0,0,0,.08); }
.tab { padding: 10px 24px; border-radius: 8px; cursor: pointer; font-size: 14px; font-weight: 500; transition: all .2s; color: #666; border: none; background: none; }
.tab:hover { background: #f0f0f0; }
.tab.active { background: linear-gradient(135deg, #667eea, #764ba2); color: white; }
.card { background: white; border-radius: 10px; box-shadow: 0 1px 4px rgba(0,0,0,.08); padding: 20px; margin-bottom: 20px; }
.card h3 { font-size: 16px; margin-bottom: 15px; color: #333; border-left: 3px solid #667eea; padding-left: 10px; }
.stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; }
.stat-item { background: linear-gradient(135deg, #f5f7fa, #c3cfe2); border-radius: 10px; padding: 18px; text-align: center; }
.stat-item .value { font-size: 28px; font-weight: 700; color: #333; }
.stat-item .label { font-size: 13px; color: #666; margin-top: 5px; }
.toolbar { display: flex; gap: 10px; margin-bottom: 15px; flex-wrap: wrap; align-items: center; }
.toolbar input, .toolbar select { padding: 8px 12px; border: 1px solid #d9d9d9; border-radius: 6px; font-size: 13px; outline: none; transition: border-color .2s; }
.toolbar input:focus, .toolbar select:focus { border-color: #667eea; }
.toolbar button { padding: 8px 18px; border: none; border-radius: 6px; cursor: pointer; font-size: 13px; font-weight: 500; transition: all .2s; }
.btn-primary { background: linear-gradient(135deg, #667eea, #764ba2); color: white; }
.btn-primary:hover { opacity: .9; transform: translateY(-1px); }
.btn-secondary { background: #f0f0f0; color: #333; }
.btn-secondary:hover { background: #e0e0e0; }
.btn-danger { background: #ff4d4f; color: white; }
.btn-danger:hover { opacity: .9; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
table th { background: #fafafa; padding: 10px 12px; text-align: left; font-weight: 600; border-bottom: 2px solid #f0f0f0; white-space: nowrap; }
table td { padding: 10px 12px; border-bottom: 1px solid #f0f0f0; vertical-align: top; }
table tr:hover { background: #f8f9ff; }
.msg-content { max-width: 400px; word-break: break-all; }
.msg-text { color: #333; }
.msg-media { color: #999; font-size: 12px; margin-top: 3px; }
.msg-img-wrap { margin-top: 5px; }
.msg-img { max-width: 150px; max-height: 150px; border-radius: 6px; cursor: pointer; border: 1px solid #eee; transition: transform .2s; }
.msg-img:hover { transform: scale(1.5); z-index: 999; position: relative; box-shadow: 0 4px 12px rgba(0,0,0,.3); }
.msg-media-tag { display: inline-block; background: #f0f0f0; color: #666; padding: 2px 6px; border-radius: 4px; font-size: 12px; margin: 2px 2px; }
.msg-reply { background: #f5f5f5; border-left: 3px solid #ddd; padding: 4px 8px; margin-top: 4px; font-size: 12px; color: #666; border-radius: 0 4px 4px 0; }
.violation-mark { margin-top: 6px; padding: 6px 8px; background: #fff1f0; border-left: 3px solid #ff4d4f; border-radius: 4px; font-size: 12px; color: #a8071a; }
.config-input { width: 100%; padding: 8px; border: 1px solid #d9d9d9; border-radius: 6px; font-size: 13px; }
.help-text { color: #888; font-size: 12px; margin-top: 4px; line-height: 1.6; }
.severity-high { color: #ff4d4f; font-weight: 600; }
.severity-medium { color: #fa8c16; font-weight: 600; }
.severity-low { color: #faad14; }
.severity-critical { color: #cf1322; font-weight: 700; }
.pagination { display: flex; justify-content: center; gap: 5px; margin-top: 15px; }
.pagination button { padding: 6px 14px; border: 1px solid #d9d9d9; border-radius: 6px; background: white; cursor: pointer; font-size: 13px; }
.pagination button.active { background: #667eea; color: white; border-color: #667eea; }
.pagination button:disabled { opacity: .5; cursor: not-allowed; }
.empty { text-align: center; padding: 40px; color: #999; }
.badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 12px; font-weight: 500; }
.badge-high { background: #fff1f0; color: #ff4d4f; }
.badge-medium { background: #fff7e6; color: #fa8c16; }
.badge-low { background: #fffbe6; color: #faad14; }
.badge-critical { background: #ffccc7; color: #cf1322; }
.badge-info { background: #e6f7ff; color: #1890ff; }
.panel { display: none; }
.panel.active { display: block; }
.loading { text-align: center; padding: 20px; color: #999; }
.group-tag { display: inline-block; background: #e6f7ff; color: #1890ff; padding: 2px 8px; border-radius: 4px; font-size: 12px; margin-right: 5px; cursor: pointer; }
.group-tag.active { background: #1890ff; color: white; }
.alert-item { border-left: 4px solid #ff4d4f; padding: 12px 15px; margin-bottom: 10px; background: #fff1f0; border-radius: 0 8px 8px 0; }
.alert-item.medium { border-left-color: #fa8c16; background: #fff7e6; }
.alert-item.low { border-left-color: #faad14; background: #fffbe6; }
</style>
</head>
<body>

<div class="header">
    <h1>QQ群聊监控系统</h1>
    <div class="status">
        <span><span class="status-dot" id="wsStatus"></span><span id="wsStatusText">连接中...</span></span>
        <span id="currentTime"></span>
    </div>
</div>

<div class="container">
    <div class="tabs">
        <button class="tab active" onclick="switchTab('dashboard')">数据概览</button>
        <button class="tab" onclick="switchTab('messages')">聊天记录</button>
        <button class="tab" onclick="switchTab('alerts')">违规告警</button>
        <button class="tab" onclick="switchTab('groups')">群组管理</button>
        <button class="tab" onclick="switchTab('settings')">系统配置</button>
        <button class="tab" onclick="switchTab('aisettings')">AI设置</button>
        <button class="tab" onclick="switchTab('secondaryai')">二次审核AI</button>
    </div>

    <!-- 数据概览 -->
    <div class="panel active" id="panel-dashboard">
        <div class="card">
            <h3>系统状态</h3>
            <div class="stats-grid" id="statsGrid">
                <div class="stat-item"><div class="value" id="statGroups">-</div><div class="label">监控群数</div></div>
                <div class="stat-item"><div class="value" id="statMessages">-</div><div class="label">消息总数</div></div>
                <div class="stat-item"><div class="value" id="statAlerts">-</div><div class="label">违规告警</div></div>
                <div class="stat-item"><div class="value" id="statStorage">-</div><div class="label">存储使用</div></div>
                <div class="stat-item"><div class="value" id="statPending">-</div><div class="label">待审查消息</div></div>
                <div class="stat-item"><div class="value" id="statQQSent">-</div><div class="label">QQ通知</div></div>
                <div class="stat-item"><div class="value" id="statEmailSent">-</div><div class="label">邮件通知</div></div>
                <div class="stat-item"><div class="value" id="statPushSent">-</div><div class="label">推送通知</div></div>
            </div>
        </div>
        <div class="card">
            <h3>最近告警</h3>
            <div id="recentAlerts"><div class="empty">暂无告警</div></div>
        </div>
    </div>

    <!-- 聊天记录 -->
    <div class="panel" id="panel-messages">
        <div class="card">
            <h3>聊天记录查询</h3>
            <div class="toolbar">
                <span>群组筛选:</span>
                <div id="groupFilters"></div>
            </div>
            <div class="toolbar">
                <input type="text" id="searchKeyword" placeholder="搜索关键词..." style="width:200px">
                <input type="text" id="searchUser" placeholder="QQ号" style="width:120px">
                <input type="datetime-local" id="searchStart" style="width:180px">
                <input type="datetime-local" id="searchEnd" style="width:180px">
                <button class="btn-primary" onclick="searchMessages(1)">搜索</button>
                <button class="btn-secondary" onclick="resetSearch()">重置</button>
            </div>
            <div id="messagesTable"></div>
            <div id="messagesPagination"></div>
        </div>
    </div>

    <!-- 违规告警 -->
    <div class="panel" id="panel-alerts">
        <div class="card">
            <h3>违规告警记录</h3>
            <div class="toolbar">
                <select id="alertSeverity">
                    <option value="">全部级别</option>
                    <option value="critical">严重</option>
                    <option value="high">高</option>
                    <option value="medium">中</option>
                    <option value="low">低</option>
                </select>
                <select id="alertCategory">
                    <option value="">全部分类</option>
                    <option value="fraud_ad">诈骗广告/引流推广</option>
                    <option value="illegal_trade">违法交易</option>
                    <option value="pornographic">色情低俗</option>
                    <option value="violence_threat">暴力威胁</option>
                    <option value="personal_attack">人身攻击</option>
                    <option value="privacy">隐私泄露</option>
                    <option value="minor_risk">未成年人风险</option>
                    <option value="political">政治敏感</option>
                    <option value="gambling">赌博博彩</option>
                    <option value="spam">恶意刷屏</option>
                    <option value="other">其他风险</option>
                </select>
                <select id="alertSecondary">
                    <option value="">全部复核状态</option>
                    <option value="confirmed">二次复核确认违规</option>
                    <option value="suspected">二次复核疑似违规</option>
                    <option value="likely_false_positive">二次复核可能误报</option>
                    <option value="secondary_unavailable">二次复核不可用</option>
                    <option value="not_reviewed">未二次复核</option>
                </select>
                <button class="btn-primary" onclick="loadAlerts()">刷新</button>
            </div>
            <div id="alertsList"></div>
        </div>
    </div>

    <!-- 群组管理 -->
    <div class="panel" id="panel-groups">
        <div class="card">
            <h3>监控群组列表</h3>
            <div id="groupsList"></div>
        </div>
    </div>

    <!-- AI设置 -->
    <div class="panel" id="panel-settings">
        <div class="card">
            <h3>系统配置</h3>
            <table style="max-width:760px">
                <tr><td style="padding:10px;font-weight:bold;width:160px">监控QQ群</td>
                    <td style="padding:10px">
                        <input class="config-input" id="configMonitorGroups" placeholder="多个群号用英文逗号分隔，例如 123456,987654">
                        <div class="help-text">保存后立即更新监听范围；新增群会从下一条新消息开始接收。</div>
                    </td></tr>
                <tr><td style="padding:10px;font-weight:bold">QQ私聊通知</td>
                    <td style="padding:10px">
                        <label><input type="checkbox" id="configQQAlertEnabled"> 启用违规后QQ私聊通知</label>
                    </td></tr>
                <tr><td style="padding:10px;font-weight:bold">通知接收QQ</td>
                    <td style="padding:10px">
                        <input class="config-input" id="configQQRecipients" placeholder="多个QQ号用英文逗号分隔，例如 123456,987654">
                        <div class="help-text">这是接收违规告警的QQ号，不是切换机器人登录账号。机器人登录账号需要在NapCat里切换。</div>
                    </td></tr>
                <tr><td style="padding:10px;font-weight:bold">聊天记录TXT目录</td>
                    <td style="padding:10px">
                        <input class="config-input" id="configExportDir" placeholder="例如 ./聊天记录 或 自定义聊天记录目录">
                        <div class="help-text">这里控制人类可读TXT聊天记录的保存位置。底层JSON数据目录不建议运行中修改。</div>
                    </td></tr>
            </table>
            <div class="toolbar">
                <button class="btn-primary" onclick="saveSystemConfig()">保存系统配置</button>
                <button class="btn-secondary" onclick="loadSystemConfig()">重新加载</button>
                <button class="btn-secondary" onclick="openFolderPicker()">选择文件夹</button>
                <button class="btn-primary" onclick="syncExportNow()">立即同步保存聊天记录</button>
                <button class="btn-primary" onclick="transferExportDir()">一键转移聊天记录目录</button>
                <button class="btn-secondary" onclick="cleanupStorage()">清理/压缩旧存储</button>
                <span id="systemConfigResult"></span>
            </div>
            <div id="folderPicker" style="display:none;margin-top:12px;padding:12px;border:1px solid #e8e8e8;border-radius:8px;background:#fafafa">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
                    <strong>选择聊天记录保存目录</strong>
                    <button class="btn-secondary" onclick="closeFolderPicker()">关闭</button>
                </div>
                <div class="help-text" id="folderCurrent"></div>
                <div id="folderList" style="margin-top:8px;max-height:260px;overflow:auto"></div>
            </div>
        </div>
    </div>

    <div class="panel" id="panel-aisettings">
        <div class="card">
            <h3>AI审查配置</h3>
            <div class="toolbar">
                <label style="margin-right:10px">
                    <input type="checkbox" id="aiEnabled" onchange="toggleAI()">
                    启用AI审查
                </label>
                <button class="btn-primary" onclick="saveAIConfig()">保存配置</button>
                <button class="btn-secondary" onclick="testAIConnection()">测试连接</button>
                <button class="btn-secondary" onclick="runAIReviewNow()">立即审查待审查消息</button>
            </div>
            <table style="max-width:700px">
                <tr><td style="padding:10px;font-weight:bold;width:140px">预设方案</td>
                    <td style="padding:10px">
                        <select id="aiPreset" onchange="applyPreset()" style="padding:6px 10px;border:1px solid #d9d9d9;border-radius:6px;width:100%">
                            <option value="">自定义</option>
                            <option value="ollama">本地Ollama</option>
                            <option value="qwen">通义千问API</option>
                        </select>
                    </td></tr>
                <tr><td style="padding:10px;font-weight:bold">API地址</td>
                    <td style="padding:10px"><input type="text" id="aiApiBase" style="width:100%;padding:8px;border:1px solid #d9d9d9;border-radius:6px" placeholder="http://localhost:11434/v1"></td></tr>
                <tr><td style="padding:10px;font-weight:bold">API Key</td>
                    <td style="padding:10px"><input type="password" id="aiApiKey" style="width:100%;padding:8px;border:1px solid #d9d9d9;border-radius:6px" placeholder="ollama 或 你的API Key"></td></tr>
                <tr><td style="padding:10px;font-weight:bold">模型名称</td>
                    <td style="padding:10px"><input type="text" id="aiModel" style="width:100%;padding:8px;border:1px solid #d9d9d9;border-radius:6px" placeholder="qwen2.5"></td></tr>
                <tr><td style="padding:10px;font-weight:bold">审查间隔(分钟)</td>
                    <td style="padding:10px"><input type="number" id="aiInterval" style="width:100px;padding:8px;border:1px solid #d9d9d9;border-radius:6px" min="1" max="60" value="5"></td></tr>
                <tr><td style="padding:10px;font-weight:bold">系统提示词</td>
                    <td style="padding:10px"><textarea id="aiPrompt" rows="4" style="width:100%;padding:8px;border:1px solid #d9d9d9;border-radius:6px;font-size:13px"></textarea></td></tr>
            </table>
            <div id="aiTestResult" style="margin-top:15px"></div>
        </div>
    </div>

    <div class="panel" id="panel-secondaryai">
        <div class="card">
            <h3>二次审核AI配置</h3>
            <div class="toolbar">
                <label style="margin-right:10px">
                    <input type="checkbox" id="secondaryAiEnabled">
                    启用二次AI审核
                </label>
                <button class="btn-primary" onclick="saveSecondaryAIConfig()">保存配置</button>
                <button class="btn-secondary" onclick="testSecondaryAIConnection()">测试连接</button>
            </div>
            <table style="max-width:760px">
                <tr><td style="padding:10px;font-weight:bold;width:150px">预设方案</td>
                    <td style="padding:10px">
                        <select id="secondaryAiPreset" onchange="applySecondaryPreset()" style="padding:6px 10px;border:1px solid #d9d9d9;border-radius:6px;width:100%">
                            <option value="">自定义</option>
                            <option value="ollama">本地Ollama</option>
                            <option value="qwen">通义千问API</option>
                        </select>
                    </td></tr>
                <tr><td style="padding:10px;font-weight:bold">API地址</td>
                    <td style="padding:10px"><input type="text" id="secondaryAiApiBase" class="config-input" placeholder="http://localhost:11434/v1"></td></tr>
                <tr><td style="padding:10px;font-weight:bold">API Key</td>
                    <td style="padding:10px"><input type="password" id="secondaryAiApiKey" class="config-input" placeholder="ollama 或 你的API Key"></td></tr>
                <tr><td style="padding:10px;font-weight:bold">模型名称</td>
                    <td style="padding:10px"><input type="text" id="secondaryAiModel" class="config-input" placeholder="qwen2.5"></td></tr>
                <tr><td style="padding:10px;font-weight:bold">系统提示词</td>
                    <td style="padding:10px"><textarea id="secondaryAiPrompt" rows="4" class="config-input" style="font-size:13px"></textarea>
                    <div class="help-text">二次审核只处理首次AI已经判定有风险的消息。这里可以使用更强、更慢或更贵的模型。</div></td></tr>
            </table>
            <div id="secondaryAiResult" style="margin-top:15px"></div>
        </div>
    </div>
</div>

<script>
const API = '';
let currentGroup = null;
let currentPage = 1;

function updateTime() {
    document.getElementById('currentTime').textContent = new Date().toLocaleString('zh-CN');
}
setInterval(updateTime, 1000);
updateTime();

function switchTab(name) {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
    event.target.classList.add('active');
    document.getElementById('panel-' + name).classList.add('active');
    if (name === 'dashboard') loadDashboard();
    if (name === 'messages') { loadGroupFilters(); searchMessages(1); }
    if (name === 'alerts') loadAlerts();
    if (name === 'groups') loadGroups();
    if (name === 'settings') loadSystemConfig();
    if (name === 'aisettings') loadAISettings();
    if (name === 'secondaryai') loadSecondaryAISettings();
}

async function api(url, opts = {}) {
    try {
        const resp = await fetch(API + url, opts);
        return await resp.json();
    } catch(e) {
        console.error('API error:', e);
        return { error: e.message };
    }
}

async function loadDashboard() {
    const data = await api('/api/stats');
    if (data.error) return;
    document.getElementById('statGroups').textContent = data.total_groups || 0;
    document.getElementById('statMessages').textContent = data.total_messages || 0;
    document.getElementById('statAlerts').textContent = data.total_alerts || 0;
    document.getElementById('statStorage').textContent = (data.storage_used_mb || 0).toFixed(1) + ' MB';
    document.getElementById('statPending').textContent = data.pending_review || 0;
    document.getElementById('statQQSent').textContent = data.alert_stats?.qq_sent || 0;
    document.getElementById('statEmailSent').textContent = data.alert_stats?.email_sent || 0;
    document.getElementById('statPushSent').textContent = data.alert_stats?.push_sent || 0;

    // WS状态
    const wsOnline = data.ws_connected;
    document.getElementById('wsStatus').className = 'status-dot ' + (wsOnline ? 'online' : 'offline');
    document.getElementById('wsStatusText').textContent = wsOnline ? '已连接' : '未连接';

    // 最近告警
    const alerts = await api('/api/alerts?limit=5');
    const container = document.getElementById('recentAlerts');
    if (alerts.length === 0) {
        container.innerHTML = '<div class="empty">暂无告警</div>';
    } else {
        container.innerHTML = alerts.map(a => renderAlertItem(a)).join('');
    }
}

async function loadGroupFilters() {
    const groups = await api('/api/groups');
    const container = document.getElementById('groupFilters');
    container.innerHTML = '<span class="group-tag ' + (currentGroup === null ? 'active' : '') + '" onclick="selectGroup(null)">全部</span>' +
        groups.map(g => `<span class="group-tag ${currentGroup === g.group_id ? 'active' : ''}" onclick="selectGroup(${g.group_id})">群${g.group_id} (${g.message_count})</span>`).join('');
}

function selectGroup(gid) {
    currentGroup = gid;
    loadGroupFilters();
    searchMessages(1);
}

async function searchMessages(page) {
    currentPage = page;
    const params = new URLSearchParams({
        page: page,
        page_size: 50,
        keyword: document.getElementById('searchKeyword').value,
        user_id: document.getElementById('searchUser').value,
        start_time: document.getElementById('searchStart').value.replace('T', ' '),
        end_time: document.getElementById('searchEnd').value.replace('T', ' '),
    });
    if (currentGroup !== null) params.set('group_id', currentGroup);
    params.set('include_alerts', '1');

    const data = await api('/api/messages?' + params.toString());
    const container = document.getElementById('messagesTable');

    if (!data.messages || data.messages.length === 0) {
        container.innerHTML = '<div class="empty">暂无聊天记录</div>';
        document.getElementById('messagesPagination').innerHTML = '';
        return;
    }

    let html = '<table><thead><tr><th>时间</th><th>群号</th><th>发送者</th><th>内容</th></tr></thead><tbody>';
    data.messages.forEach(m => {
        const content = m.content || {};
        const text = (content.text || '').replace(/</g, '&lt;');
        const segs = content.segments || [];

        // 构建媒体HTML
        let mediaHtml = '';
        segs.forEach(s => {
            if (s.type === 'image') {
                const imgSrc = s.local_path || s.url || '';
                if (imgSrc) {
                    mediaHtml += `<div class="msg-img-wrap"><img class="msg-img" src="${imgSrc}" onclick="window.open(this.src)" onerror="this.style.display='none'"></div>`;
                } else {
                    mediaHtml += '<span class="msg-media-tag">[图片]</span>';
                }
            } else if (s.type === 'face') {
                mediaHtml += `<span class="msg-media-tag">[表情:${s.data?.id || ''}]</span>`;
            } else if (s.type === 'reply') {
                mediaHtml += `<div class="msg-reply">回复: ${(s.data?.msg_preview || '').replace(/</g,'&lt;')}</div>`;
            } else if (s.type !== 'text' && s.summary) {
                mediaHtml += `<span class="msg-media-tag">${s.summary}</span>`;
            }
        });

        const violation = m.violation_summary || null;
        const violationHtml = violation ? `<div class="violation-mark">
            违规：${String(categoryLabel(violation.category, violation.category_label)).replace(/</g,'&lt;')}
            · ${String(violation.violation_type || '').replace(/</g,'&lt;')}
            · ${String(violation.secondary_status_label || '未二次复核').replace(/</g,'&lt;')}
        </div>` : '';

        html += `<tr>
            <td style="white-space:nowrap">${m.datetime || ''}</td>
            <td>群${m.group_id || ''}</td>
            <td><strong>${(m.card || m.nickname || '未知').replace(/</g,'&lt;')}</strong><br><small style="color:#999">QQ:${m.user_id || ''}</small></td>
            <td class="msg-content"><div class="msg-text">${text}</div>${mediaHtml}${violationHtml}</td>
        </tr>`;
    });
    html += '</tbody></table>';
    container.innerHTML = html;

    // 分页
    const total = data.total_pages || 1;
    let pagHtml = '<div class="pagination">';
    pagHtml += `<button ${page <= 1 ? 'disabled' : ''} onclick="searchMessages(${page-1})">上一页</button>`;
    for (let i = Math.max(1, page-3); i <= Math.min(total, page+3); i++) {
        pagHtml += `<button class="${i === page ? 'active' : ''}" onclick="searchMessages(${i})">${i}</button>`;
    }
    pagHtml += `<button ${page >= total ? 'disabled' : ''} onclick="searchMessages(${page+1})">下一页</button>`;
    pagHtml += `<span style="margin-left:10px;color:#999">共 ${data.total} 条</span>`;
    pagHtml += '</div>';
    document.getElementById('messagesPagination').innerHTML = pagHtml;
}

function resetSearch() {
    document.getElementById('searchKeyword').value = '';
    document.getElementById('searchUser').value = '';
    document.getElementById('searchStart').value = '';
    document.getElementById('searchEnd').value = '';
    currentGroup = null;
    searchMessages(1);
}

async function loadAlerts() {
    const severity = document.getElementById('alertSeverity').value;
    const category = document.getElementById('alertCategory').value;
    const secondary = document.getElementById('alertSecondary').value;
    const params = new URLSearchParams({ limit: 100 });
    if (severity) params.set('severity', severity);
    if (category) params.set('category', category);
    if (secondary) params.set('secondary_status', secondary);
    const alerts = await api('/api/alerts?' + params.toString());
    const container = document.getElementById('alertsList');

    if (!alerts || alerts.length === 0) {
        container.innerHTML = '<div class="empty">暂无告警记录</div>';
        return;
    }
    container.innerHTML = alerts.map(a => renderAlertItem(a)).join('');
}

function renderAlertItem(a) {
    const msg = a.message || {};
    const sevClass = a.severity || 'medium';
    const time = a.review_time || a.time || '';
    const groupId = msg.group_id || a.group_id || '?';
    const userId = msg.user_id || a.user_id || '?';
    const nickname = msg.card || msg.nickname || a.card || a.nickname || '未知';
    const msgTime = msg.datetime || a.datetime || '';
    const content = a.content_preview || msg.content?.text || a.matched_word || '';
    const category = categoryLabel(a.category, a.category_label);
    const secondary = a.secondary_status_label || '未二次复核';
    const reportBasis = a.report_basis_label || '按当前结果上报';
    const notifyText = a.should_notify === false ? '不通知' : (a.notified ? '已通知' : '未通知');
    return `<div class="alert-item ${sevClass}">
        <div style="display:flex;justify-content:space-between;align-items:center">
            <strong><span class="badge badge-${sevClass}">${sevClass.toUpperCase()}</span> ${category} · ${a.violation_type || a.type || '未知'}</strong>
            <small style="color:#999">${time}</small>
        </div>
        <div style="margin-top:6px;font-size:12px;color:#555">
            <span>二次复核：${String(secondary).replace(/</g,'&lt;')}</span> ·
            <span>上报依据：${String(reportBasis).replace(/</g,'&lt;')}</span> ·
            <span>通知状态：${notifyText}</span>
        </div>
        <div style="margin-top:8px">
            <span>群${groupId}</span> ·
            <span>${String(nickname).replace(/</g,'&lt;')}</span> (QQ:${userId}) ·
            <span>${msgTime}</span>
        </div>
        <div style="margin-top:6px;padding:8px;background:rgba(255,255,255,.6);border-radius:4px">
            ${String(content).replace(/</g,'&lt;')}
        </div>
        ${a.reason ? '<div style="margin-top:4px;font-size:12px;color:#666">判定: ' + a.reason.replace(/</g,'&lt;') + '</div>' : ''}
        ${a.secondary_reason ? '<div style="margin-top:4px;font-size:12px;color:#3b5bdb">二次复核: ' + a.secondary_reason.replace(/</g,'&lt;') + '</div>' : ''}
    </div>`;
}

async function loadGroups() {
    const groups = await api('/api/groups');
    const container = document.getElementById('groupsList');
    if (!groups || groups.length === 0) {
        container.innerHTML = '<div class="empty">暂无监控群组</div>';
        return;
    }
    let html = '<table><thead><tr><th>群号</th><th>消息数</th><th>最新消息</th><th>可查日期</th></tr></thead><tbody>';
    groups.forEach(g => {
        html += `<tr>
            <td><strong>群${g.group_id}</strong></td>
            <td>${g.message_count}</td>
            <td>${g.latest_message || '-'}</td>
            <td>${g.available_dates ? g.available_dates.slice(0,5).join(', ') : '-'}</td>
        </tr>`;
    });
    html += '</tbody></table>';
    container.innerHTML = html;
}

// 初始化
loadDashboard();

// ==================== AI设置 ====================
const AI_PRESETS = {
    ollama: { api_base: 'http://localhost:11434/v1', api_key: 'ollama', model: 'qwen2.5' },
    qwen: { api_base: 'https://dashscope.aliyuncs.com/compatible-mode/v1', api_key: '', model: 'qwen-plus' }
};

const CATEGORY_LABELS = {
    fraud_ad: '诈骗广告/引流推广',
    illegal_trade: '违法交易',
    pornographic: '色情低俗',
    violence_threat: '暴力威胁',
    personal_attack: '人身攻击',
    privacy: '隐私泄露',
    minor_risk: '未成年人风险',
    political: '政治敏感',
    gambling: '赌博博彩',
    spam: '恶意刷屏',
    other: '其他风险'
};

function categoryLabel(value, label) {
    return label || CATEGORY_LABELS[value] || '其他风险';
}

function loadAISettings() {
    api('/api/ai/config').then(data => {
        document.getElementById('aiEnabled').checked = data.enabled;
        document.getElementById('aiApiBase').value = data.api_base || '';
        document.getElementById('aiApiKey').value = data.api_key || '';
        document.getElementById('aiModel').value = data.model || '';
        document.getElementById('aiInterval').value = data.review_interval_minutes || 5;
        document.getElementById('aiPrompt').value = data.system_prompt || '';
        // 检测预设
        const presetSel = document.getElementById('aiPreset');
        presetSel.value = '';
        for (const [k, v] of Object.entries(AI_PRESETS)) {
            if (data.api_base === v.api_base && data.model === v.model) {
                presetSel.value = k; break;
            }
        }
    });
}

function applyPreset() {
    const preset = document.getElementById('aiPreset').value;
    if (!preset || !AI_PRESETS[preset]) return;
    const p = AI_PRESETS[preset];
    document.getElementById('aiApiBase').value = p.api_base;
    document.getElementById('aiApiKey').value = p.api_key;
    document.getElementById('aiModel').value = p.model;
}

function applySecondaryPreset() {
    const preset = document.getElementById('secondaryAiPreset').value;
    if (!preset || !AI_PRESETS[preset]) return;
    const p = AI_PRESETS[preset];
    document.getElementById('secondaryAiApiBase').value = p.api_base;
    document.getElementById('secondaryAiApiKey').value = p.api_key;
    document.getElementById('secondaryAiModel').value = p.model;
}

async function loadSecondaryAISettings() {
    const data = await api('/api/secondary-ai/config');
    if (data.error) return;
    document.getElementById('secondaryAiEnabled').checked = data.enabled !== false;
    document.getElementById('secondaryAiApiBase').value = data.api_base || '';
    document.getElementById('secondaryAiApiKey').value = data.api_key || '';
    document.getElementById('secondaryAiModel').value = data.model || '';
    document.getElementById('secondaryAiPrompt').value = data.system_prompt || '';

    const presetSel = document.getElementById('secondaryAiPreset');
    presetSel.value = '';
    for (const [k, v] of Object.entries(AI_PRESETS)) {
        if (data.api_base === v.api_base && data.model === v.model) {
            presetSel.value = k; break;
        }
    }
}

async function saveSecondaryAIConfig() {
    const payload = {
        enabled: document.getElementById('secondaryAiEnabled').checked,
        api_base: document.getElementById('secondaryAiApiBase').value.trim(),
        api_key: document.getElementById('secondaryAiApiKey').value.trim(),
        model: document.getElementById('secondaryAiModel').value.trim(),
        system_prompt: document.getElementById('secondaryAiPrompt').value.trim()
    };
    const result = await api('/api/secondary-ai/config', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload)
    });
    const el = document.getElementById('secondaryAiResult');
    if (result.success) {
        el.innerHTML = '<div style="padding:10px;background:#f6ffed;border:1px solid #b7eb8f;border-radius:6px;color:#52c41a">' + result.message + '</div>';
    } else {
        el.innerHTML = '<div style="padding:10px;background:#fff2f0;border:1px solid #ffccc7;border-radius:6px;color:#ff4d4f">' + (result.message || result.error || '').replace(/</g,'&lt;') + '</div>';
    }
}

async function testSecondaryAIConnection() {
    const el = document.getElementById('secondaryAiResult');
    el.innerHTML = '<div style="padding:10px;color:#999">正在测试二次审核AI连接...</div>';
    await saveSecondaryAIConfig();
    const result = await api('/api/secondary-ai/test', {method: 'POST'});
    if (result.success) {
        el.innerHTML = '<div style="padding:10px;background:#f6ffed;border:1px solid #b7eb8f;border-radius:6px;color:#52c41a">连接成功! 模型回复: ' + (result.response || '').replace(/</g,'&lt;') + '</div>';
    } else {
        el.innerHTML = '<div style="padding:10px;background:#fff2f0;border:1px solid #ffccc7;border-radius:6px;color:#ff4d4f">连接失败: ' + (result.error || '').replace(/</g,'&lt;') + '</div>';
    }
}

function parseIdList(text) {
    return (text || '').split(/[,，\s]+/)
        .map(x => x.trim())
        .filter(Boolean)
        .map(x => Number(x))
        .filter(x => Number.isInteger(x) && x > 0);
}

async function loadSystemConfig() {
    const data = await api('/api/system/config');
    if (data.error) return;
    document.getElementById('configMonitorGroups').value = (data.monitor_groups || []).join(', ');
    document.getElementById('configQQAlertEnabled').checked = !!data.qq_alert_enabled;
    document.getElementById('configQQRecipients').value = (data.qq_recipients || []).join(', ');
    document.getElementById('configExportDir').value = data.export_dir || '';
}

async function saveSystemConfig() {
    const resultEl = document.getElementById('systemConfigResult');
    const payload = {
        monitor_groups: parseIdList(document.getElementById('configMonitorGroups').value),
        qq_alert_enabled: document.getElementById('configQQAlertEnabled').checked,
        qq_recipients: parseIdList(document.getElementById('configQQRecipients').value),
        export_dir: document.getElementById('configExportDir').value.trim()
    };
    const result = await api('/api/system/config', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload)
    });
    if (result.success) {
        resultEl.innerHTML = '<span style="color:#52c41a">已保存并立即生效</span>';
        loadDashboard();
        loadGroupFilters();
    } else {
        resultEl.innerHTML = '<span style="color:#ff4d4f">保存失败：' + (result.error || result.message || '').replace(/</g,'&lt;') + '</span>';
    }
}

async function openFolderPicker(path = '') {
    document.getElementById('folderPicker').style.display = 'block';
    const result = await api('/api/folders' + (path ? ('?path=' + encodeURIComponent(path)) : ''));
    const currentEl = document.getElementById('folderCurrent');
    const listEl = document.getElementById('folderList');
    if (result.error) {
        currentEl.textContent = '读取目录失败：' + result.error;
        listEl.innerHTML = '';
        return;
    }
    currentEl.textContent = result.current ? ('当前目录：' + result.current) : '请选择磁盘或目录';
    let html = '';
    if (result.parent) {
        html += `<div style="padding:6px"><button class="btn-secondary" onclick="openFolderPicker('${String(result.parent).replace(/\\/g,'\\\\').replace(/'/g,"\\'")}')">上一级</button></div>`;
    }
    if (result.current) {
        html += `<div style="padding:6px"><button class="btn-primary" onclick="selectExportFolder('${String(result.current).replace(/\\/g,'\\\\').replace(/'/g,"\\'")}')">使用当前目录</button></div>`;
    }
    result.dirs.forEach(d => {
        const safePath = String(d.path).replace(/\\/g,'\\\\').replace(/'/g,"\\'");
        html += `<div style="padding:6px;border-bottom:1px solid #eee;display:flex;justify-content:space-between;gap:8px">
            <span>${String(d.name).replace(/</g,'&lt;')}</span>
            <span>
                <button class="btn-secondary" onclick="openFolderPicker('${safePath}')">打开</button>
                <button class="btn-primary" onclick="selectExportFolder('${safePath}')">选择</button>
            </span>
        </div>`;
    });
    listEl.innerHTML = html || '<div class="empty">没有可访问的子目录</div>';
}

function selectExportFolder(path) {
    document.getElementById('configExportDir').value = path;
    closeFolderPicker();
}

function closeFolderPicker() {
    document.getElementById('folderPicker').style.display = 'none';
}

async function syncExportNow() {
    const resultEl = document.getElementById('systemConfigResult');
    resultEl.innerHTML = '<span style="color:#999">正在同步保存聊天记录...</span>';
    await saveSystemConfig();
    const result = await api('/api/export/sync', {method: 'POST'});
    if (result.success) {
        resultEl.innerHTML = '<span style="color:#52c41a">同步完成：已导出 ' + result.exported + ' 条聊天记录</span>';
    } else {
        resultEl.innerHTML = '<span style="color:#ff4d4f">同步失败：' + (result.error || '').replace(/</g,'&lt;') + '</span>';
    }
}

async function transferExportDir() {
    const resultEl = document.getElementById('systemConfigResult');
    const target = document.getElementById('configExportDir').value.trim();
    if (!target) {
        resultEl.innerHTML = '<span style="color:#ff4d4f">请先选择或填写新的聊天记录TXT目录</span>';
        return;
    }
    if (!confirm('确定要把已有聊天记录TXT文件转移到新目录吗？')) return;
    resultEl.innerHTML = '<span style="color:#999">正在转移聊天记录目录...</span>';
    const result = await api('/api/export/transfer', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({target_dir: target})
    });
    if (result.success) {
        document.getElementById('configExportDir').value = result.export_dir || target;
        resultEl.innerHTML = '<span style="color:#52c41a">转移完成：移动 ' + result.moved + ' 项，当前目录已更新</span>';
    } else {
        resultEl.innerHTML = '<span style="color:#ff4d4f">转移失败：' + (result.error || '').replace(/</g,'&lt;') + '</span>';
    }
}

async function cleanupStorage() {
    const resultEl = document.getElementById('systemConfigResult');
    resultEl.innerHTML = '<span style="color:#999">正在清理和压缩旧存储...</span>';
    const result = await api('/api/storage/cleanup', {method: 'POST'});
    if (result.error) {
        resultEl.innerHTML = '<span style="color:#ff4d4f">清理失败：' + result.error.replace(/</g,'&lt;') + '</span>';
        return;
    }
    resultEl.innerHTML = '<span style="color:#52c41a">清理完成：压缩 '
        + (result.compressed || 0) + ' 个，删除 '
        + (result.deleted || 0) + ' 个，释放 '
        + (result.freed_mb || 0) + ' MB</span>';
    loadDashboard();
}

async function saveAIConfig() {
    const payload = {
        enabled: document.getElementById('aiEnabled').checked,
        api_base: document.getElementById('aiApiBase').value.trim(),
        api_key: document.getElementById('aiApiKey').value.trim(),
        model: document.getElementById('aiModel').value.trim(),
        review_interval: parseInt(document.getElementById('aiInterval').value) || 5,
        system_prompt: document.getElementById('aiPrompt').value.trim()
    };
    const result = await api('/api/ai/config', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload)
    });
    const el = document.getElementById('aiTestResult');
    if (result.success) {
        el.innerHTML = '<div style="padding:10px;background:#f6ffed;border:1px solid #b7eb8f;border-radius:6px;color:#52c41a">' + result.message + '</div>';
    } else {
        el.innerHTML = '<div style="padding:10px;background:#fff2f0;border:1px solid #ffccc7;border-radius:6px;color:#ff4d4f">' + result.message + '</div>';
    }
}

async function testAIConnection() {
    const el = document.getElementById('aiTestResult');
    el.innerHTML = '<div style="padding:10px;color:#999">正在测试连接...</div>';
    // 先保存再测试
    await saveAIConfig();
    const result = await api('/api/ai/test', {method: 'POST'});
    if (result.success) {
        el.innerHTML = '<div style="padding:10px;background:#f6ffed;border:1px solid #b7eb8f;border-radius:6px;color:#52c41a">连接成功! 模型回复: ' + (result.response || '').replace(/</g,'&lt;') + '</div>';
    } else {
        el.innerHTML = '<div style="padding:10px;background:#fff2f0;border:1px solid #ffccc7;border-radius:6px;color:#ff4d4f">连接失败: ' + (result.error || '').replace(/</g,'&lt;') + '</div>';
    }
}

async function runAIReviewNow() {
    const el = document.getElementById('aiTestResult');
    el.innerHTML = '<div style="padding:10px;color:#999">正在执行AI审查...</div>';
    const result = await api('/api/ai/review', {method: 'POST'});
    if (result.success) {
        el.innerHTML = '<div style="padding:10px;background:#f6ffed;border:1px solid #b7eb8f;border-radius:6px;color:#52c41a">'
            + '审查完成：审查 ' + result.reviewed_count + ' 条，发现 ' + result.violation_count + ' 条违规，剩余待审查 ' + result.pending_count + ' 条。'
            + '</div>';
        loadDashboard();
    } else {
        el.innerHTML = '<div style="padding:10px;background:#fff2f0;border:1px solid #ffccc7;border-radius:6px;color:#ff4d4f">审查失败: '
            + (result.error || result.message || '').replace(/</g,'&lt;')
            + '</div>';
    }
}

function toggleAI() {
    // 仅切换checkbox状态，不立即保存
}
</script>
</body>
</html>
"""


class WebPanel:
    """Web查询面板"""

    def __init__(self, store: MessageStore, host: str = "0.0.0.0",
                 port: int = 8080, debug: bool = False):
        self.store = store
        self.host = host
        self.port = port
        self.debug = debug

        self._app = Flask(__name__, template_folder="../templates")
        self._app.config['JSON_AS_ASCII'] = False
        CORS(self._app)

        # 外部状态引用（由主程序设置）
        self._napcat_client = None
        self._compliance_manager = None
        self._alert_manager = None
        self._exporter = None

        self._register_routes()

    def set_components(self, napcat_client=None, compliance_manager=None,
                       alert_manager=None, exporter=None):
        """设置外部组件引用"""
        if napcat_client is not None:
            self._napcat_client = napcat_client
        if compliance_manager is not None:
            self._compliance_manager = compliance_manager
        if alert_manager is not None:
            self._alert_manager = alert_manager
        if exporter is not None:
            self._exporter = exporter

    def _register_routes(self) -> None:
        """注册路由"""

        @self._app.route('/')
        def index():
            return render_template_string(DASHBOARD_HTML)

        @self._app.route('/api/stats')
        def api_stats():
            stats = self.store.get_statistics()
            stats["pending_review"] = 0
            stats["ws_connected"] = False

            if self._compliance_manager:
                stats["pending_review"] = self._compliance_manager.get_pending_count()
            if self._napcat_client:
                napcat_stats = self._napcat_client.get_stats()
                stats["ws_connected"] = napcat_stats.get("connection_count", 0) > 0
                stats["total_messages"] = napcat_stats.get("total_messages", stats["total_messages"])

            if self._alert_manager:
                stats["alert_stats"] = self._alert_manager.get_stats()

            return jsonify(stats)

        @self._app.route('/api/messages')
        def api_messages():
            group_id = request.args.get('group_id', type=int)
            user_id = request.args.get('user_id', type=int)
            keyword = request.args.get('keyword', '')
            start_time = request.args.get('start_time', '')
            end_time = request.args.get('end_time', '')
            page = request.args.get('page', 1, type=int)
            page_size = request.args.get('page_size', 50, type=int)
            include_alerts = request.args.get('include_alerts', '0') in ('1', 'true', 'yes')

            result = self.store.query_messages(
                group_id=group_id,
                user_id=user_id,
                keyword=keyword,
                start_time=start_time,
                end_time=end_time,
                page=page,
                page_size=page_size,
                include_alerts=include_alerts
            )
            return jsonify(result)

        @self._app.route('/api/messages/file')
        def api_messages_file():
            """从历史文件查询"""
            group_id = request.args.get('group_id', type=int)
            date = request.args.get('date', '')
            user_id = request.args.get('user_id', type=int)
            keyword = request.args.get('keyword', '')

            if not group_id or not date:
                return jsonify({"error": "缺少group_id或date参数"}), 400

            messages = self.store.query_from_file(
                group_id=group_id,
                date=date,
                user_id=user_id,
                keyword=keyword
            )
            return jsonify({"messages": messages, "total": len(messages)})

        @self._app.route('/api/alerts')
        def api_alerts():
            limit = request.args.get('limit', 50, type=int)
            group_id = request.args.get('group_id', type=int)
            severity = request.args.get('severity', '')
            category = request.args.get('category', '')
            secondary_status = request.args.get('secondary_status', '')

            alerts = self.store.get_alerts(
                limit=limit,
                group_id=group_id,
                severity=severity,
                category=category,
                secondary_status=secondary_status
            )
            return jsonify(alerts)

        @self._app.route('/api/groups')
        def api_groups():
            groups = self.store.get_monitored_groups()
            return jsonify(groups)

        @self._app.route('/api/system/config', methods=['GET'])
        def api_system_config_get():
            if not self._compliance_manager:
                return jsonify({"error": "合规管理器未初始化"}), 400

            cfg = self._compliance_manager._config
            napcat_cfg = cfg.get("napcat", {})
            qq_cfg = cfg.get("alert", {}).get("qq", {})
            storage_cfg = cfg.get("storage", {})
            return jsonify({
                "monitor_groups": napcat_cfg.get("monitor_groups", []),
                "qq_alert_enabled": qq_cfg.get("enabled", False),
                "qq_recipients": qq_cfg.get("recipient_user_ids", []),
                "export_dir": storage_cfg.get("export_dir", "")
            })

        @self._app.route('/api/system/config', methods=['POST'])
        def api_system_config_set():
            if not self._compliance_manager:
                return jsonify({"success": False, "error": "合规管理器未初始化"}), 400

            data = request.get_json(force=True)
            monitor_groups = self._parse_id_list(data.get("monitor_groups", []))
            qq_recipients = self._parse_id_list(data.get("qq_recipients", []))
            qq_enabled = bool(data.get("qq_alert_enabled", False))
            export_dir = str(data.get("export_dir", "") or "").strip()

            if not monitor_groups:
                return jsonify({"success": False, "error": "至少需要填写一个监控群号"}), 400

            cfg = self._compliance_manager._config
            cfg.setdefault("napcat", {})["monitor_groups"] = monitor_groups
            qq_cfg = cfg.setdefault("alert", {}).setdefault("qq", {})
            qq_cfg["enabled"] = qq_enabled
            qq_cfg["recipient_user_ids"] = qq_recipients
            if export_dir:
                export_dir = self._normalize_path(export_dir)
                cfg.setdefault("storage", {})["export_dir"] = export_dir

            if self._napcat_client:
                self._napcat_client.monitor_groups = set(monitor_groups)
                logger.info(f"Web配置已更新监控群: {monitor_groups}")

            if self._alert_manager:
                self._alert_manager.update_qq_recipients(qq_enabled, qq_recipients)
            if export_dir and self._exporter:
                self._exporter.update_export_dir(export_dir)

            self._save_runtime_config(cfg)
            return jsonify({
                "success": True,
                "monitor_groups": monitor_groups,
                "qq_alert_enabled": qq_enabled,
                "qq_recipients": qq_recipients,
                "export_dir": export_dir
            })

        @self._app.route('/api/folders')
        def api_folders():
            """列出本机目录，供网页端选择聊天记录保存位置"""
            path = request.args.get("path", "").strip()
            try:
                if not path:
                    dirs = []
                    if os.name == "nt":
                        for code in range(ord("A"), ord("Z") + 1):
                            drive = f"{chr(code)}:\\"
                            if os.path.exists(drive):
                                dirs.append({"name": drive, "path": drive})
                    else:
                        dirs.append({"name": "/", "path": "/"})
                    return jsonify({"current": "", "parent": "", "dirs": dirs})

                current = self._normalize_path(path)
                if not os.path.isdir(current):
                    return jsonify({"error": "目录不存在或不可访问"}), 400

                dirs = []
                for name in sorted(os.listdir(current), key=lambda x: x.lower()):
                    full_path = os.path.join(current, name)
                    if os.path.isdir(full_path):
                        dirs.append({"name": name, "path": full_path})
                parent = os.path.dirname(current.rstrip("\\/"))
                if parent == current:
                    parent = ""
                return jsonify({"current": current, "parent": parent, "dirs": dirs})
            except Exception as e:
                return jsonify({"error": str(e)}), 400

        @self._app.route('/api/export/sync', methods=['POST'])
        def api_export_sync():
            """立即把内存中的聊天记录同步导出为TXT"""
            if not self._exporter:
                return jsonify({"success": False, "error": "聊天记录导出器未初始化"}), 400
            try:
                exported = self._exporter.export_history_from_store(self.store)
                return jsonify({"success": True, "exported": exported})
            except Exception as e:
                return jsonify({"success": False, "error": str(e)}), 500

        @self._app.route('/api/export/transfer', methods=['POST'])
        def api_export_transfer():
            """一键转移聊天记录TXT目录"""
            if not self._compliance_manager:
                return jsonify({"success": False, "error": "合规管理器未初始化"}), 400
            data = request.get_json(force=True)
            target_dir = self._normalize_path(str(data.get("target_dir", "") or "").strip())
            if not target_dir:
                return jsonify({"success": False, "error": "目标目录不能为空"}), 400

            cfg = self._compliance_manager._config
            old_dir = self._normalize_path(cfg.get("storage", {}).get("export_dir", ""))
            try:
                os.makedirs(target_dir, exist_ok=True)
                moved = self._move_directory_contents(old_dir, target_dir)
                cfg.setdefault("storage", {})["export_dir"] = target_dir
                if self._exporter:
                    self._exporter.update_export_dir(target_dir)
                    self._exporter.export_history_from_store(self.store)
                self._save_runtime_config(cfg)
                return jsonify({
                    "success": True,
                    "moved": moved,
                    "old_dir": old_dir,
                    "export_dir": target_dir
                })
            except Exception as e:
                return jsonify({"success": False, "error": str(e)}), 500

        @self._app.route('/api/groups/<int:group_id>/dates')
        def api_group_dates(group_id):
            dates = self.store.get_available_dates(group_id)
            return jsonify(dates)

        @self._app.route('/api/storage')
        def api_storage():
            storage_info = self.store.check_storage()
            return jsonify(storage_info)

        @self._app.route('/api/storage/cleanup', methods=['POST'])
        def api_storage_cleanup():
            result = self.store.cleanup_old_files()
            return jsonify(result)

        @self._app.route('/api/test-alert', methods=['POST'])
        def api_test_alert():
            if self._alert_manager:
                self._alert_manager.send_test_alert()
                return jsonify({"status": "ok", "message": "测试告警已发送"})
            return jsonify({"error": "告警管理器未初始化"}), 400

        @self._app.route('/api/rules/reload', methods=['POST'])
        def api_rules_reload():
            if self._compliance_manager:
                self._compliance_manager.detector.reload_rules()
                return jsonify({"status": "ok", "message": "规则已重新加载"})
            return jsonify({"error": "合规管理器未初始化"}), 400

        @self._app.route('/api/images/<path:img_path>')
        def api_serve_image(img_path):
            """提供本地图片访问"""
            full_path = os.path.join(self.store.data_dir, img_path)
            if not os.path.exists(full_path):
                return jsonify({"error": "图片不存在"}), 404
            directory = os.path.dirname(full_path)
            filename = os.path.basename(full_path)
            return send_from_directory(directory, filename)

        @self._app.route('/api/ai/config', methods=['GET'])
        def api_ai_config_get():
            if self._compliance_manager:
                return jsonify(self._compliance_manager.get_ai_config())
            return jsonify({"error": "合规管理器未初始化"}), 400

        @self._app.route('/api/ai/config', methods=['POST'])
        def api_ai_config_set():
            if not self._compliance_manager:
                return jsonify({"error": "合规管理器未初始化"}), 400
            data = request.get_json(force=True)
            result = self._compliance_manager.update_ai_config(
                api_base=data.get('api_base'),
                api_key=data.get('api_key'),
                model=data.get('model'),
                system_prompt=data.get('system_prompt'),
                enabled=data.get('enabled'),
                review_interval=data.get('review_interval')
            )
            return jsonify(result)

        @self._app.route('/api/secondary-ai/config', methods=['GET'])
        def api_secondary_ai_config_get():
            if self._compliance_manager:
                return jsonify(self._compliance_manager.get_secondary_ai_config())
            return jsonify({"error": "合规管理器未初始化"}), 400

        @self._app.route('/api/secondary-ai/config', methods=['POST'])
        def api_secondary_ai_config_set():
            if not self._compliance_manager:
                return jsonify({"error": "合规管理器未初始化"}), 400
            data = request.get_json(force=True)
            result = self._compliance_manager.update_secondary_ai_config(
                enabled=data.get('enabled'),
                api_base=data.get('api_base'),
                api_key=data.get('api_key'),
                model=data.get('model'),
                system_prompt=data.get('system_prompt')
            )
            return jsonify(result)

        @self._app.route('/api/secondary-ai/test', methods=['POST'])
        def api_secondary_ai_test():
            if self._compliance_manager:
                result = self._compliance_manager.test_secondary_ai_connection()
                return jsonify(result)
            return jsonify({"error": "合规管理器未初始化"}), 400

        @self._app.route('/api/ai/test', methods=['POST'])
        def api_ai_test():
            if self._compliance_manager:
                result = self._compliance_manager.test_ai_connection()
                return jsonify(result)
            return jsonify({"error": "合规管理器未初始化"}), 400

        @self._app.route('/api/ai/review', methods=['POST'])
        def api_ai_review():
            if not self._compliance_manager:
                return jsonify({"success": False, "error": "合规管理器未初始化"}), 400
            before = self._compliance_manager.get_pending_count()
            violations = self._compliance_manager.do_ai_review()
            status = self._compliance_manager.get_ai_status()
            last_error = status.get("last_error", "")
            return jsonify({
                "success": not bool(last_error),
                "error": last_error,
                "reviewed_count": before - status.get("pending_count", 0) if not last_error else 0,
                "violation_count": len(violations),
                "pending_count": status.get("pending_count", 0),
                "status": status
            })

    def _parse_id_list(self, value) -> list:
        """解析前端传入的QQ号/群号列表"""
        if value is None:
            return []
        if isinstance(value, str):
            raw_items = value.replace("，", ",").split(",")
        elif isinstance(value, list):
            raw_items = value
        else:
            raw_items = [value]

        result = []
        for item in raw_items:
            text = str(item).strip()
            if not text:
                continue
            try:
                num = int(text)
                if num > 0 and num not in result:
                    result.append(num)
            except ValueError:
                continue
        return result

    def _normalize_path(self, path: str) -> str:
        """规范化网页端输入的本地目录路径"""
        path = path.strip().strip('"').strip("'")
        if not path:
            return ""
        if not os.path.isabs(path):
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            path = os.path.join(base_dir, path)
        return os.path.abspath(path)

    def _move_directory_contents(self, old_dir: str, target_dir: str) -> int:
        """把旧导出目录内容移动到新目录"""
        if not old_dir or not os.path.isdir(old_dir):
            return 0
        old_abs = os.path.abspath(old_dir)
        target_abs = os.path.abspath(target_dir)
        if old_abs.lower() == target_abs.lower():
            return 0
        if target_abs.lower().startswith(old_abs.lower() + os.sep):
            raise ValueError("目标目录不能是当前聊天记录目录的子目录")

        moved = 0
        for name in os.listdir(old_abs):
            src = os.path.join(old_abs, name)
            dst = os.path.join(target_abs, name)
            if os.path.exists(dst):
                if os.path.isdir(src) and os.path.isdir(dst):
                    moved += self._move_directory_contents(src, dst)
                    try:
                        os.rmdir(src)
                    except OSError:
                        pass
                else:
                    base, ext = os.path.splitext(name)
                    idx = 1
                    while os.path.exists(dst):
                        dst = os.path.join(target_abs, f"{base}_{idx}{ext}")
                        idx += 1
                    shutil.move(src, dst)
                    moved += 1
            else:
                shutil.move(src, dst)
                moved += 1
        return moved

    def _save_runtime_config(self, config: Dict[str, Any]) -> None:
        """保存运行时配置"""
        config_path = config.get("_config_path", "")
        if not config_path:
            return
        save_data = {k: v for k, v in config.items() if not k.startswith("_")}
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(save_data, f, ensure_ascii=False, indent=4)
        logger.info("系统配置已通过Web面板保存")

    def start(self) -> None:
        """启动Web面板"""
        logger.info(f"Web查询面板启动: http://{self.host}:{self.port}")
        self._app.run(
            host=self.host,
            port=self.port,
            debug=self.debug,
            threaded=True,
            use_reloader=False
        )

    def start_in_thread(self) -> None:
        """在后台线程中启动Web面板"""
        import threading
        thread = threading.Thread(
            target=self.start,
            daemon=True,
            name="WebPanel"
        )
        thread.start()
        logger.info(f"Web面板已启动，访问地址: http://localhost:{self.port}")
