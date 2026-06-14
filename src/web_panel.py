"""
Web查询面板
提供浏览器端的聊天记录查询、告警查看、统计概览等功能
"""

import os
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
        <button class="tab" onclick="switchTab('aisettings')">AI设置</button>
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
    if (name === 'aisettings') loadAISettings();
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

        html += `<tr>
            <td style="white-space:nowrap">${m.datetime || ''}</td>
            <td>群${m.group_id || ''}</td>
            <td><strong>${(m.card || m.nickname || '未知').replace(/</g,'&lt;')}</strong><br><small style="color:#999">QQ:${m.user_id || ''}</small></td>
            <td class="msg-content"><div class="msg-text">${text}</div>${mediaHtml}</td>
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
    const params = new URLSearchParams({ limit: 100 });
    if (severity) params.set('severity', severity);
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
    return `<div class="alert-item ${sevClass}">
        <div style="display:flex;justify-content:space-between;align-items:center">
            <strong><span class="badge badge-${sevClass}">${sevClass.toUpperCase()}</span> ${a.violation_type || a.type || '未知'}</strong>
            <small style="color:#999">${time}</small>
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

        self._register_routes()

    def set_components(self, napcat_client=None, compliance_manager=None,
                       alert_manager=None):
        """设置外部组件引用"""
        self._napcat_client = napcat_client
        self._compliance_manager = compliance_manager
        self._alert_manager = alert_manager

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

            result = self.store.query_messages(
                group_id=group_id,
                user_id=user_id,
                keyword=keyword,
                start_time=start_time,
                end_time=end_time,
                page=page,
                page_size=page_size
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

            alerts = self.store.get_alerts(
                limit=limit,
                group_id=group_id,
                severity=severity
            )
            return jsonify(alerts)

        @self._app.route('/api/groups')
        def api_groups():
            groups = self.store.get_monitored_groups()
            return jsonify(groups)

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
