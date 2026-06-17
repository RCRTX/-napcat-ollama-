"""
NapCat WebSocket 消息收集模块
通过NapCat的OneBot 11 WebSocket接口接收QQ群消息
"""

import json
import time
import threading
import traceback
from typing import Callable, Optional, Dict, Any, List
from datetime import datetime

import websocket

from .logger import setup_logger

logger = setup_logger("napcat")


class NapCatClient:
    """NapCat WebSocket客户端，用于接收QQ群消息"""

    def __init__(self, ws_url: str, token: str = "",
                 monitor_groups: List[int] = None,
                 http_url: str = ""):
        """
        初始化NapCat客户端

        Args:
            ws_url: WebSocket地址，如 ws://localhost:3001
            token: 访问令牌（可选）
            monitor_groups: 要监控的群号列表
            http_url: HTTP API地址，用于主动调用接口
        """
        self.ws_url = ws_url
        self.token = token
        self.monitor_groups = set(monitor_groups or [])
        self.http_url = http_url.rstrip("/")

        self._ws: Optional[websocket.WebSocketApp] = None
        self._running = False
        self._reconnect_interval = 5
        self._max_reconnect_interval = 60
        self._current_reconnect_interval = self._reconnect_interval
        self._message_callbacks: List[Callable] = []
        self._private_message_callbacks: List[Callable] = []
        self._connection_callbacks: List[Callable] = []
        self._bot_qq = ""
        self._disconnection_callbacks: List[Callable] = []

        # 消息缓冲区（用于暂存未处理的消息）
        self._message_buffer: List[Dict[str, Any]] = []
        self._buffer_lock = threading.Lock()

        # 统计信息
        self._stats = {
            "total_messages": 0,
            "filtered_messages": 0,
            "last_message_time": None,
            "connection_count": 0,
            "errors": 0
        }

    def on_message(self, callback: Callable) -> None:
        """注册消息回调函数"""
        self._message_callbacks.append(callback)

    def on_private_message(self, callback: Callable) -> None:
        """注册私聊消息回调函数"""
        self._private_message_callbacks.append(callback)

    def on_connect(self, callback: Callable) -> None:
        """注册连接成功回调"""
        self._connection_callbacks.append(callback)

    def on_disconnect(self, callback: Callable) -> None:
        """注册断开连接回调"""
        self._disconnection_callbacks.append(callback)

    def start(self) -> None:
        """启动WebSocket连接"""
        self._running = True
        self._current_reconnect_interval = self._reconnect_interval

        # WebSocket头部（用于鉴权）
        headers = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        self._ws = websocket.WebSocketApp(
            self.ws_url,
            header=headers,
            on_open=self._on_open,
            on_message=self._on_ws_message,
            on_error=self._on_error,
            on_close=self._on_close
        )

        # 在单独的线程中运行WebSocket
        ws_thread = threading.Thread(
            target=self._ws.run_forever,
            daemon=True,
            name="NapCat-WS"
        )
        ws_thread.start()
        logger.info(f"NapCat WebSocket客户端已启动，连接地址: {self.ws_url}")

    def stop(self) -> None:
        """停止WebSocket连接"""
        self._running = False
        if self._ws:
            self._ws.close()
        logger.info("NapCat WebSocket客户端已停止")

    def get_buffered_messages(self) -> List[Dict[str, Any]]:
        """获取并清空消息缓冲区"""
        with self._buffer_lock:
            messages = self._message_buffer.copy()
            self._message_buffer.clear()
        return messages

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return self._stats.copy()

    def _on_open(self, ws) -> None:
        """WebSocket连接成功回调"""
        self._current_reconnect_interval = self._reconnect_interval
        self._stats["connection_count"] += 1
        logger.info("已连接到NapCat WebSocket服务")

        # 触发注册的连接回调
        for callback in self._connection_callbacks:
            try:
                callback()
            except Exception as e:
                logger.error(f"连接回调执行失败: {e}")

    def _on_ws_message(self, ws, message: str) -> None:
        """收到WebSocket消息回调"""
        try:
            data = json.loads(message)
            post_type = data.get("post_type", "")

            # 自动从消息中捕获机器人QQ号
            self_id = data.get("self_id", "")
            if self_id and not self._bot_qq:
                self._bot_qq = str(self_id)
                logger.info(f"从WebSocket消息中获取到机器人QQ号: {self._bot_qq}")

            if post_type == "message":
                self._handle_message(data)
            elif post_type == "meta_event":
                # 心跳等元事件，忽略
                pass
            elif post_type == "notice":
                self._handle_notice(data)

        except json.JSONDecodeError:
            logger.warning(f"收到非JSON消息: {message[:200]}")
        except Exception as e:
            logger.error(f"处理消息时出错: {e}\n{traceback.format_exc()}")
            self._stats["errors"] += 1

    def _handle_message(self, data: Dict[str, Any]) -> None:
        """处理收到的消息"""
        message_type = data.get("message_type", "")
        group_id = data.get("group_id", 0)

        # 私聊消息用于确认大文件保存等管理操作
        if message_type == "private":
            text = self._extract_plain_text(data.get("message", []), data.get("raw_message", ""))
            parsed_private = {
                "type": "private_message",
                "user_id": data.get("user_id", 0),
                "time": data.get("time", 0),
                "datetime": datetime.fromtimestamp(data.get("time", time.time())).strftime("%Y-%m-%d %H:%M:%S"),
                "text": text,
                "raw": data
            }
            for callback in self._private_message_callbacks:
                try:
                    callback(parsed_private)
                except Exception as e:
                    logger.error(f"私聊消息回调执行失败: {e}")
            return

        # 只处理群消息且在监控列表中的群
        if message_type != "group":
            return
        if self.monitor_groups and group_id not in self.monitor_groups:
            self._stats["filtered_messages"] += 1
            return

        self._stats["total_messages"] += 1
        self._stats["last_message_time"] = datetime.now().isoformat()

        # 解析消息内容
        parsed = self._parse_message(data)

        # 加入缓冲区
        with self._buffer_lock:
            self._message_buffer.append(parsed)

        # 触发回调
        for callback in self._message_callbacks:
            try:
                callback(parsed)
            except Exception as e:
                logger.error(f"消息回调执行失败: {e}")

    def _handle_notice(self, data: Dict[str, Any]) -> None:
        """处理通知事件（如成员变动、群公告等）"""
        notice_type = data.get("notice_type", "")
        group_id = data.get("group_id", 0)

        if self.monitor_groups and group_id not in self.monitor_groups:
            return

        if notice_type in ("group_increase", "group_decrease", "group_ban"):
            parsed = {
                "type": "notice",
                "notice_type": notice_type,
                "group_id": group_id,
                "user_id": data.get("user_id", 0),
                "operator_id": data.get("operator_id", 0),
                "sub_type": data.get("sub_type", ""),
                "time": data.get("time", 0),
                "raw": data
            }
            with self._buffer_lock:
                self._message_buffer.append(parsed)

            for callback in self._message_callbacks:
                try:
                    callback(parsed)
                except Exception as e:
                    logger.error(f"通知回调执行失败: {e}")

    def _parse_message(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        解析消息为统一格式

        返回格式:
        {
            "type": "message",
            "message_id": 12345,
            "group_id": 123456789,
            "user_id": 987654321,
            "nickname": "用户昵称",
            "card": "群名片",
            "role": "member",
            "time": 1234567890,
            "datetime": "2024-01-01 12:00:00",
            "message_type": "group",
            "sub_type": "normal",
            "raw_message": "原始消息文本",
            "content": {
                "text": "纯文本内容",
                "segments": [
                    {"type": "text", "data": {"text": "hello"}},
                    {"type": "image", "data": {"url": "...", "file": "..."}},
                    {"type": "face", "data": {"id": "123"}},
                    {"type": "at", "data": {"qq": "123456"}},
                    {"type": "reply", "data": {"id": "123", "msg": "..."}}
                ]
            },
            "raw": {...}  # 原始数据
        }
        """
        message_segments = data.get("message", [])
        raw_message = data.get("raw_message", "")
        time_ts = data.get("time", 0)
        group_id = data.get("group_id", 0)

        # 解析消息段
        segments = []
        text_parts = []
        has_image = False
        has_face = False
        image_urls = []
        file_count = 0

        for seg in message_segments:
            seg_type = seg.get("type", "")
            seg_data = seg.get("data", {})

            if seg_type == "text":
                text = seg_data.get("text", "").strip()
                if text:
                    text_parts.append(text)
                    segments.append({"type": "text", "data": {"text": text}})

            elif seg_type == "image":
                has_image = True
                url = seg_data.get("url", "")
                file = seg_data.get("file", "")
                image_urls.append(url)
                segments.append({
                    "type": "image",
                    "data": {
                        "url": url,
                        "file": file,
                        "summary": "[图片]"
                    }
                })

            elif seg_type == "face":
                has_face = True
                face_id = seg_data.get("id", "")
                segments.append({
                    "type": "face",
                    "data": {
                        "id": face_id,
                        "summary": f"[表情:{face_id}]"
                    }
                })

            elif seg_type == "at":
                qq = seg_data.get("qq", "all")
                name = seg_data.get("name", "")
                segments.append({
                    "type": "at",
                    "data": {"qq": qq, "name": name}
                })

            elif seg_type == "reply":
                msg_id = seg_data.get("id", "")
                msg_text = seg_data.get("msg", "")[:100]
                segments.append({
                    "type": "reply",
                    "data": {"id": msg_id, "msg_preview": msg_text}
                })

            elif seg_type == "record":
                url = seg_data.get("url", "")
                segments.append({
                    "type": "voice",
                    "data": {"url": url, "summary": "[语音消息]"}
                })

            elif seg_type == "video":
                url = seg_data.get("url", "")
                segments.append({
                    "type": "video",
                    "data": {
                        "url": url,
                        "file": seg_data.get("file", ""),
                        "name": seg_data.get("name", seg_data.get("file", "")),
                        "size": seg_data.get("size", 0),
                        "summary": "[视频]"
                    }
                })

            elif seg_type == "file":
                file_count += 1
                name = seg_data.get("name", "") or seg_data.get("file", "") or "文件"
                segments.append({
                    "type": "file",
                    "data": {
                        "url": seg_data.get("url", ""),
                        "file": seg_data.get("file", ""),
                        "name": name,
                        "size": seg_data.get("size", 0),
                        "file_id": seg_data.get("file_id", ""),
                        "summary": f"[文件:{name}]"
                    }
                })

            elif seg_type == "forward":
                segments.append({
                    "type": "forward",
                    "data": {"summary": "[合并转发消息]"}
                })

            elif seg_type == "json":
                data_str = seg_data.get("data", "")
                segments.append({
                    "type": "json",
                    "data": {"raw": data_str, "summary": "[JSON消息]"}
                })

            elif seg_type == "xml":
                data_str = seg_data.get("data", "")
                segments.append({
                    "type": "xml",
                    "data": {"raw": data_str, "summary": "[XML消息]"}
                })

            else:
                segments.append({
                    "type": seg_type,
                    "data": seg_data,
                    "summary": f"[{seg_type}]"
                })

        # 构建纯文本摘要
        content_summary = " ".join(text_parts)
        if has_image:
            content_summary += f" [包含{len(image_urls)}张图片]"
        if has_face:
            content_summary += " [包含表情]"
        if file_count:
            content_summary += f" [包含{file_count}个文件]"

        # 时间格式化
        try:
            dt = datetime.fromtimestamp(time_ts)
            datetime_str = dt.strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, OSError):
            datetime_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 发送者信息
        sender = data.get("sender", {})
        nickname = sender.get("nickname", "")
        card = sender.get("card", "") or nickname
        role = sender.get("role", "member")

        return {
            "type": "message",
            "message_id": data.get("message_id", 0),
            "group_id": group_id,
            "user_id": data.get("user_id", 0),
            "nickname": nickname,
            "card": card,
            "role": role,
            "time": time_ts,
            "datetime": datetime_str,
            "message_type": "group",
            "sub_type": data.get("sub_type", "normal"),
            "raw_message": raw_message,
            "content": {
                "text": content_summary.strip(),
                "segments": segments,
                "has_image": has_image,
                "has_face": has_face,
                "image_urls": image_urls
            },
            "raw": data
        }

    def _extract_plain_text(self, message_segments: List[Dict[str, Any]], raw_message: str = "") -> str:
        """从消息段中提取纯文本"""
        parts = []
        for seg in message_segments or []:
            if seg.get("type") == "text":
                text = seg.get("data", {}).get("text", "").strip()
                if text:
                    parts.append(text)
        return " ".join(parts).strip() or raw_message.strip()

    def _on_error(self, ws, error) -> None:
        """WebSocket错误回调"""
        self._stats["errors"] += 1
        logger.error(f"WebSocket错误: {error}")

    def _on_close(self, ws, close_status_code, close_msg) -> None:
        """WebSocket关闭回调"""
        logger.warning(f"WebSocket连接已关闭 (code={close_status_code}, msg={close_msg})")

        for callback in self._disconnection_callbacks:
            try:
                callback()
            except Exception as e:
                logger.error(f"断开回调执行失败: {e}")

        # 自动重连
        if self._running:
            logger.info(f"{self._current_reconnect_interval}秒后尝试重连...")
            time.sleep(self._current_reconnect_interval)
            self._current_reconnect_interval = min(
                self._current_reconnect_interval * 2,
                self._max_reconnect_interval
            )
            self.start()

    def send_group_message(self, group_id: int, message: str) -> bool:
        """通过HTTP API发送群消息"""
        if not self.http_url:
            logger.warning("未配置HTTP API地址，无法发送消息")
            return False

        try:
            import requests
            url = f"{self.http_url}/send_group_msg"
            headers = {}
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"

            payload = {
                "group_id": group_id,
                "message": [{"type": "text", "data": {"text": message}}]
            }

            resp = requests.post(url, json=payload, headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "ok":
                    logger.info(f"已向群 {group_id} 发送消息")
                    return True
                else:
                    logger.error(f"发送消息失败: {data}")
                    return False
            else:
                logger.error(f"发送消息HTTP错误: {resp.status_code}")
                return False

        except Exception as e:
            logger.error(f"发送消息异常: {e}")
            return False

    def send_private_message(self, user_id: int, message: str) -> bool:
        """通过HTTP API发送私聊消息"""
        if not self.http_url:
            logger.warning("未配置HTTP API地址，无法发送私聊消息")
            return False

        try:
            import requests
            url = f"{self.http_url}/send_private_msg"
            headers = {}
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"

            payload = {
                "user_id": user_id,
                "message": [{"type": "text", "data": {"text": message}}]
            }

            resp = requests.post(url, json=payload, headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "ok":
                    logger.info(f"已向用户 {user_id} 发送私聊消息")
                    return True
                else:
                    logger.error(f"发送私聊消息失败: {data}")
                    return False
            else:
                logger.error(f"发送私聊消息HTTP错误: {resp.status_code}")
                return False

        except Exception as e:
            logger.error(f"发送私聊消息异常: {e}")
            return False

    def get_login_info(self) -> Dict[str, Any]:
        """获取机器人登录信息（QQ号等）"""
        if not self.http_url:
            return {}
        try:
            import requests
            url = f"{self.http_url}/get_login_info"
            headers = {}
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"
            resp = requests.get(url, headers=headers, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "ok":
                    return data.get("data", {})
        except Exception as e:
            logger.error(f"获取登录信息失败: {e}")
        return {}

    @property
    def bot_qq(self) -> str:
        """获取机器人QQ号（缓存）"""
        if not hasattr(self, '_bot_qq'):
            self._bot_qq = ""
        if not self._bot_qq:
            # 先尝试从WebSocket消息中获取（已由_on_ws_message设置）
            # 再尝试HTTP API
            info = self.get_login_info()
            qq = str(info.get("user_id", ""))
            if qq:
                self._bot_qq = qq
                logger.info(f"通过HTTP API获取到机器人QQ号: {self._bot_qq}")
            # 如果HTTP也失败，_bot_qq保持空，等待WebSocket消息设置
        return self._bot_qq
