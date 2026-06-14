"""
人类可读聊天记录导出模块
将聊天记录导出为人类可读的txt文件，图片保存到子文件夹
"""

import os
import time
import threading
import requests
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

from .logger import setup_logger

logger = setup_logger("exporter")


class HumanReadableExporter:
    """人类可读聊天记录导出器"""

    def __init__(self, export_dir: str, max_storage_mb: int = 500):
        self.export_dir = export_dir
        self.max_storage_mb = max_storage_mb

        # 每个群当天的文件句柄缓存
        self._file_handles: Dict[str, Any] = {}
        self._file_lock = threading.Lock()

        # 已导出的消息ID（去重）
        self._exported_ids: set = set()
        self._exported_lock = threading.Lock()

        # 图片计数器（每个群每天从1开始）
        self._img_counters: Dict[str, int] = {}

        os.makedirs(export_dir, exist_ok=True)
        logger.info(f"人类可读导出器初始化完成，导出目录: {export_dir}")

    def export_message(self, message: Dict[str, Any]) -> None:
        """导出一条消息到txt文件"""
        if message.get("type") != "message":
            return

        msg_key = self._get_message_key(message)
        if not msg_key:
            return

        # 去重
        with self._exported_lock:
            if msg_key in self._exported_ids:
                return
            self._exported_ids.add(msg_key)

        group_id = message.get("group_id", 0)
        dt_str = message.get("datetime", "")
        date_part = dt_str[:10] if len(dt_str) >= 10 else datetime.now().strftime("%Y-%m-%d")

        # 获取文件句柄
        file_key = f"{group_id}_{date_part}"
        file_path = self._get_file_path(group_id, date_part)

        # 构建人类可读行
        line = self._format_message_line(message, group_id, date_part)

        # 写入文件
        with self._file_lock:
            try:
                with open(file_path, 'a', encoding='utf-8') as f:
                    f.write(line + "\n")
            except Exception as e:
                logger.error(f"写入导出文件失败: {e}")

    def _get_message_key(self, message: Dict[str, Any]) -> Optional[Tuple]:
        """生成消息去重键"""
        msg_id = message.get("message_id", 0)
        group_id = message.get("group_id", 0)
        if msg_id:
            return ("id", group_id, msg_id)

        content_text = message.get("content", {}).get("text", "")
        return (
            "fallback",
            group_id,
            message.get("user_id", 0),
            message.get("time", 0),
            content_text
        )

    def _get_file_path(self, group_id: int, date_str: str) -> str:
        """获取txt文件路径"""
        group_dir = os.path.join(self.export_dir, f"群{group_id}")
        os.makedirs(group_dir, exist_ok=True)
        return os.path.join(group_dir, f"{date_str}.txt")

    def _format_message_line(self, message: Dict[str, Any],
                             group_id: int, date_str: str) -> str:
        """格式化消息为人类可读的一行"""
        dt = message.get("datetime", "")
        nickname = message.get("card") or message.get("nickname", "未知")
        user_id = message.get("user_id", 0)
        content = message.get("content", {})
        segments = content.get("segments", [])
        # content.text 是预拼接的纯文本，作为fallback
        content_text = content.get("text", "").strip()

        parts = []

        for seg in segments:
            seg_type = seg.get("type", "")
            # 兼容两种格式：精简后字段在顶层，原始数据在data子字典中
            seg_data = seg.get("data", seg)  # 如果没有data就用自身

            if seg_type == "text":
                text = seg.get("text", "") or seg_data.get("text", "")
                if text:
                    parts.append(text)
                elif content_text:
                    # 旧数据中text字段丢失，用content.text
                    parts.append(content_text)
                    content_text = ""  # 避免重复

            elif seg_type == "image":
                # 优先使用已下载的本地路径
                local_path = seg.get("local_path", "")
                img_url = seg.get("url", "") or seg_data.get("url", "")
                if local_path:
                    # 已经下载到data目录了，复制到聊天记录目录
                    dest_rel = self._copy_or_download_image(
                        local_path, img_url, group_id, date_str, user_id
                    )
                    if dest_rel:
                        parts.append(f"[图片] -> {dest_rel}")
                    else:
                        parts.append("[图片]")
                elif img_url:
                    dest_rel = self._download_image(
                        img_url, group_id, date_str, user_id
                    )
                    if dest_rel:
                        parts.append(f"[图片] -> {dest_rel}")
                    else:
                        parts.append("[图片]")
                else:
                    parts.append("[图片]")

            elif seg_type == "face":
                face_id = seg.get("id", "") or seg_data.get("id", "")
                parts.append(f"[表情:{face_id}]")

            elif seg_type == "at":
                qq = seg.get("qq", "") or seg_data.get("qq", "")
                name = seg.get("name", "") or seg_data.get("name", "")
                if name or qq:
                    parts.append(f"[@{name or qq}]")

            elif seg_type == "reply":
                msg_preview = seg.get("msg_preview", "") or seg_data.get("msg_preview", "")[:50]
                parts.append(f"[回复: {msg_preview}]")

            elif seg_type == "voice":
                parts.append("[语音消息]")

            elif seg_type == "video":
                parts.append("[视频]")

            elif seg_type == "forward":
                parts.append("[合并转发消息]")

            elif seg_type == "json":
                parts.append("[JSON消息]")

            elif seg_type == "xml":
                parts.append("[XML消息]")

            elif seg_type == "markdown":
                parts.append("[Markdown消息]")

            elif seg_type == "poke":
                parts.append("[戳一戳]")

            elif seg_type == "dice":
                parts.append("[骰子]")

            elif seg_type == "rps":
                parts.append("[猜拳]")

            else:
                summary = seg.get("summary", "") or seg_data.get("summary", "")
                if summary and summary != seg_type:
                    parts.append(f"[{summary}]")
                # 不再输出"[无法识别的内容]"，静默跳过

        # 如果segments解析后为空，fallback到raw_message
        if not parts:
            raw = message.get("raw_message", "").strip()
            if raw:
                # 去掉CQ码标签，只保留文字
                import re
                clean = re.sub(r'\[CQ:[^\]]+\]', '[消息]', raw)
                parts.append(clean)

        content_str = " ".join(parts) if parts else "[无法识别的内容]"
        return f"[{dt}] {nickname}(QQ:{user_id}): {content_str}"

    def _copy_or_download_image(self, local_path: str, img_url: str,
                                group_id: int, date_str: str,
                                user_id: int) -> Optional[str]:
        """从data目录复制已下载的图片，或从URL下载"""
        img_dir = os.path.join(self.export_dir, f"群{group_id}", "images", date_str)
        os.makedirs(img_dir, exist_ok=True)

        # 生成目标文件名
        counter_key = f"{group_id}_{date_str}"
        if counter_key not in self._img_counters:
            self._img_counters[counter_key] = 1
        else:
            self._img_counters[counter_key] += 1
        idx = self._img_counters[counter_key]

        # 从local_path推断扩展名
        ext = ".jpg"
        if local_path:
            low = local_path.lower()
            if ".gif" in low:
                ext = ".gif"
            elif ".png" in low:
                ext = ".png"
        elif img_url:
            low = img_url.lower()
            if "gif" in low:
                ext = ".gif"
            elif "png" in low:
                ext = ".png"

        filename = f"{user_id}_{idx:03d}{ext}"
        dest_path = os.path.join(img_dir, filename)

        # 已存在则跳过
        if os.path.exists(dest_path):
            rel = os.path.relpath(dest_path, os.path.join(self.export_dir, f"群{group_id}"))
            return rel.replace(os.sep, "/")

        # 尝试从data目录复制
        if local_path:
            # local_path是/api/images/...格式，转换为实际文件路径
            # 需要找到data目录的实际位置
            data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
            src_path = os.path.join(data_dir, local_path.replace("/api/images/", "").replace("/", os.sep))
            if os.path.exists(src_path):
                import shutil
                shutil.copy2(src_path, dest_path)
                rel = os.path.relpath(dest_path, os.path.join(self.export_dir, f"群{group_id}"))
                return rel.replace(os.sep, "/")

        # 从URL下载
        if img_url:
            return self._download_image(img_url, group_id, date_str, user_id)

        return None

    def _download_image(self, url: str, group_id: int,
                        date_str: str, user_id: int) -> Optional[str]:
        """下载图片到本地，返回相对路径"""
        if not url:
            return None

        try:
            img_dir = os.path.join(self.export_dir, f"群{group_id}", "images", date_str)
            os.makedirs(img_dir, exist_ok=True)

            # 生成文件名
            counter_key = f"{group_id}_{date_str}"
            if counter_key not in self._img_counters:
                self._img_counters[counter_key] = 1
            else:
                self._img_counters[counter_key] += 1
            idx = self._img_counters[counter_key]

            ext = ".jpg"
            if "gif" in url.lower():
                ext = ".gif"
            elif "png" in url.lower():
                ext = ".png"

            filename = f"{user_id}_{idx:03d}{ext}"
            local_path = os.path.join(img_dir, filename)

            # 已存在则跳过
            if os.path.exists(local_path):
                rel = os.path.relpath(local_path, os.path.join(self.export_dir, f"群{group_id}"))
                return rel.replace(os.sep, "/")

            resp = requests.get(url, timeout=10, stream=True)
            if resp.status_code == 200:
                with open(local_path, 'wb') as f:
                    for chunk in resp.iter_content(8192):
                        f.write(chunk)
                rel = os.path.relpath(local_path, os.path.join(self.export_dir, f"群{group_id}"))
                logger.debug(f"图片已导出: {local_path}")
                return rel.replace(os.sep, "/")
            else:
                return None

        except Exception as e:
            logger.debug(f"图片导出失败: {e}")
            return None

    def export_history_from_store(self, store) -> int:
        """从存储模块导出所有历史记录，启动时重建txt以避免重复追加"""
        exported = 0
        grouped_lines: Dict[str, List[str]] = {}
        seen_keys = set()

        for group_id, messages in store._index.items():
            # 按时间排序
            messages_sorted = sorted(messages, key=lambda x: x.get("time", 0))
            for msg in messages_sorted:
                try:
                    if msg.get("type") != "message":
                        continue

                    msg_key = self._get_message_key(msg)
                    if not msg_key or msg_key in seen_keys:
                        continue

                    seen_keys.add(msg_key)
                    dt_str = msg.get("datetime", "")
                    date_part = dt_str[:10] if len(dt_str) >= 10 else datetime.now().strftime("%Y-%m-%d")
                    file_path = self._get_file_path(group_id, date_part)
                    line = self._format_message_line(msg, group_id, date_part)
                    grouped_lines.setdefault(file_path, []).append(line)
                    exported += 1
                except Exception as e:
                    logger.debug(f"导出历史消息跳过: {e}")

        with self._file_lock:
            for file_path, lines in grouped_lines.items():
                try:
                    with open(file_path, 'w', encoding='utf-8') as f:
                        f.write("\n".join(lines))
                        if lines:
                            f.write("\n")
                except Exception as e:
                    logger.error(f"重建导出文件失败: {file_path}, 错误: {e}")

        with self._exported_lock:
            self._exported_ids = seen_keys

        logger.info(f"历史记录导出完成，共导出 {exported} 条")
        return exported

    def check_and_cleanup(self) -> Dict[str, Any]:
        """检查存储空间并清理旧文件"""
        total_size = 0
        for dirpath, dirnames, filenames in os.walk(self.export_dir):
            for f in filenames:
                try:
                    total_size += os.path.getsize(os.path.join(dirpath, f))
                except OSError:
                    continue

        used_mb = total_size / (1024 * 1024)
        result = {
            "used_mb": round(used_mb, 2),
            "max_mb": self.max_storage_mb,
            "needs_cleanup": used_mb > self.max_storage_mb * 0.8
        }

        if result["needs_cleanup"]:
            self._cleanup_old_files()

        return result

    def _cleanup_old_files(self) -> None:
        """清理最旧的文件直到空间足够"""
        from datetime import timedelta

        # 收集所有txt文件按日期排序
        txt_files = []
        for group_dir_name in os.listdir(self.export_dir):
            group_path = os.path.join(self.export_dir, group_dir_name)
            if not os.path.isdir(group_path):
                continue
            for fname in os.listdir(group_path):
                if fname.endswith(".txt"):
                    fpath = os.path.join(group_path, fname)
                    txt_files.append((fpath, os.path.getmtime(fpath)))

        txt_files.sort(key=lambda x: x[1])  # 按修改时间升序（最旧的在前）

        # 删除最旧的文件直到空间足够
        while txt_files:
            used_mb = self._calc_total_size() / (1024 * 1024)
            if used_mb < self.max_storage_mb * 0.7:
                break

            fpath, _ = txt_files.pop(0)
            try:
                os.remove(fpath)
                logger.info(f"清理旧文件: {fpath}")
                # 也清理对应的图片目录
                date_str = os.path.basename(fpath).replace(".txt", "")
                group_dir = os.path.dirname(fpath)
                img_dir = os.path.join(group_dir, "images", date_str)
                if os.path.exists(img_dir):
                    import shutil
                    shutil.rmtree(img_dir, ignore_errors=True)
                    logger.info(f"清理图片目录: {img_dir}")
            except Exception as e:
                logger.error(f"清理文件失败: {fpath}, {e}")

    def _calc_total_size(self) -> float:
        total = 0
        for dirpath, _, filenames in os.walk(self.export_dir):
            for f in filenames:
                try:
                    total += os.path.getsize(os.path.join(dirpath, f))
                except OSError:
                    continue
        return total
