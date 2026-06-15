"""
聊天记录存储模块
负责将消息持久化到JSON文件，并提供查询接口
支持空间管理（自动清理旧文件）
"""

import json
import os
import shutil
import gzip
import threading
import requests
import hashlib
import re
import uuid
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from collections import defaultdict

from .logger import setup_logger

logger = setup_logger("storage")


class MessageStore:
    """聊天记录存储管理器"""

    def __init__(self, data_dir: str, log_dir: str,
                 max_storage_mb: int = 500,
                 archive_days: int = 30,
                 file_rotate_hours: int = 24,
                 save_images: bool = True,
                 max_image_size_mb: int = 5,
                 save_files: bool = True,
                 large_file_confirm_mb: int = 1024,
                 max_alert_records: int = 1000):
        """
        初始化存储管理器

        Args:
            data_dir: 数据存储目录
            log_dir: 日志目录
            max_storage_mb: 最大存储空间(MB)
            archive_days: 归档天数（超过此天数的文件会被压缩）
            file_rotate_hours: 文件轮转间隔(小时)
        """
        self.data_dir = data_dir
        self.max_storage_mb = max_storage_mb
        self.archive_days = archive_days
        self.file_rotate_hours = file_rotate_hours
        self.save_images = save_images
        self.max_image_size_mb = max_image_size_mb
        self.save_files = save_files
        self.large_file_confirm_mb = large_file_confirm_mb
        self.max_alert_records = max_alert_records
        self._large_file_threshold_bytes = max(1, large_file_confirm_mb) * 1024 * 1024

        # 按群号分目录存储
        self._group_dirs: Dict[int, str] = {}
        # 当前写入文件句柄缓存
        self._file_handles: Dict[str, Any] = {}
        self._file_lock = threading.Lock()
        self._current_date: Dict[int, str] = {}

        # 内存索引（用于快速查询）
        self._index: Dict[int, List[Dict]] = defaultdict(list)
        self._index_lock = threading.Lock()
        self._max_index_per_group = 10000  # 每群最多在内存中保留的条目数

        # 已保存消息ID集合（用于去重）
        self._saved_message_ids: set = set()
        self._saved_ids_lock = threading.Lock()

        # 告警记录
        self._alerts: List[Dict] = []
        self._alerts_lock = threading.Lock()

        # 大文件待确认记录
        self._pending_files: Dict[str, Dict[str, Any]] = {}
        self._pending_lock = threading.Lock()
        self._large_file_callbacks: List[Any] = []

        # 确保目录存在
        os.makedirs(data_dir, exist_ok=True)

        # 启动时加载历史记录
        self._load_history()
        self._load_pending_files()

        logger.info(f"存储管理器初始化完成，数据目录: {data_dir}")

    def _load_history(self) -> None:
        """启动时从文件加载历史记录到内存索引"""
        if not os.path.exists(self.data_dir):
            return

        loaded_messages = 0
        loaded_alerts = 0

        # 加载各群的历史消息
        for group_name in os.listdir(self.data_dir):
            group_path = os.path.join(self.data_dir, group_name)
            if not os.path.isdir(group_path):
                continue

            try:
                group_id = int(group_name)
            except ValueError:
                # 可能是 alerts.jsonl 或其他文件
                continue

            # 加载所有历史文件
            all_files = []
            for filename in os.listdir(group_path):
                if filename.endswith(".jsonl") and not filename.startswith("alerts"):
                    all_files.append(filename)

            # 按文件名正序加载（从旧到新）
            all_files.sort()

            for filename in all_files:

                file_path = os.path.join(group_path, filename)
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                msg = json.loads(line)
                                self._index[group_id].append(msg)
                                # 记录消息ID用于去重
                                mid = msg.get("message_id", 0)
                                if mid:
                                    self._saved_message_ids.add(mid)
                                loaded_messages += 1
                            except json.JSONDecodeError:
                                continue
                except Exception as e:
                    logger.error(f"加载历史文件失败: {file_path}, 错误: {e}")

            # 裁剪到最大索引数
            if len(self._index[group_id]) > self._max_index_per_group:
                self._index[group_id] = self._index[group_id][-self._max_index_per_group:]

        # 加载历史告警
        alerts_file = os.path.join(self.data_dir, "alerts.jsonl")
        if os.path.exists(alerts_file):
            try:
                with open(alerts_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            alert = json.loads(line)
                            self._alerts.append(alert)
                            loaded_alerts += 1
                        except json.JSONDecodeError:
                            continue
                # 限制数量
                if len(self._alerts) > self.max_alert_records:
                    self._alerts = self._alerts[-self.max_alert_records:]
            except Exception as e:
                logger.error(f"加载历史告警失败: {e}")

        logger.info(f"历史记录加载完成: {loaded_messages} 条消息, {loaded_alerts} 条告警")

    def _pending_file_path(self) -> str:
        """待确认大文件记录路径"""
        return os.path.join(self.data_dir, "pending_large_files.json")

    def _load_pending_files(self) -> None:
        """加载待确认大文件记录"""
        path = self._pending_file_path()
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                self._pending_files = {str(item.get("file_id")): item for item in data if item.get("file_id")}
            elif isinstance(data, dict):
                self._pending_files = data
            logger.info(f"已加载 {len(self._pending_files)} 条待确认大文件记录")
        except Exception as e:
            logger.error(f"加载待确认大文件记录失败: {e}")

    def _save_pending_files(self) -> None:
        """保存待确认大文件记录"""
        try:
            with open(self._pending_file_path(), "w", encoding="utf-8") as f:
                json.dump(list(self._pending_files.values()), f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存待确认大文件记录失败: {e}")

    def save_message(self, message: Dict[str, Any]) -> None:
        """保存一条消息（自动去重）"""
        msg_id = message.get("message_id", 0)
        if msg_id:
            with self._saved_ids_lock:
                if msg_id in self._saved_message_ids:
                    return  # 已存在，跳过
                self._saved_message_ids.add(msg_id)

        if message.get("type") == "message":
            group_id = message.get("group_id", 0)
            self._save_to_file(group_id, message)
            self._add_to_index(group_id, message)
        elif message.get("type") == "notice":
            group_id = message.get("group_id", 0)
            self._save_to_file(group_id, message)
            self._add_to_index(group_id, message)

    def save_alert(self, alert: Dict[str, Any]) -> None:
        """保存一条告警记录"""
        with self._alerts_lock:
            self._alerts.append(alert)
            # 内存中最多保留指定数量告警
            if len(self._alerts) > self.max_alert_records:
                self._alerts = self._alerts[-self.max_alert_records:]

        # 同时写入告警文件
        alert_file = os.path.join(self.data_dir, "alerts.jsonl")
        try:
            with open(alert_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(alert, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error(f"写入告警文件失败: {e}")

    def on_large_file_pending(self, callback) -> None:
        """注册大文件待确认回调"""
        self._large_file_callbacks.append(callback)

    def get_pending_files(self) -> List[Dict[str, Any]]:
        """获取待确认文件列表"""
        with self._pending_lock:
            items = list(self._pending_files.values())
        return sorted(items, key=lambda x: x.get("created_at", ""), reverse=True)

    def confirm_pending_file(self, file_id: str) -> Dict[str, Any]:
        """确认保存待处理大文件"""
        with self._pending_lock:
            record = self._pending_files.get(file_id)
        if not record:
            return {"success": False, "error": "待确认文件不存在"}
        if record.get("status") == "saved":
            return {"success": True, "message": "文件已经保存", "record": record}
        if record.get("status") == "rejected":
            return {"success": False, "error": "文件已被拒绝保存"}

        local_path = self._download_attachment_record(record, force=True)
        with self._pending_lock:
            if local_path:
                record["status"] = "saved"
                record["local_path"] = local_path
            else:
                record["status"] = "download_failed"
            self._pending_files[file_id] = record
            self._save_pending_files()
        return {"success": bool(local_path), "record": record, "error": "" if local_path else "文件下载失败"}

    def reject_pending_file(self, file_id: str) -> Dict[str, Any]:
        """拒绝保存待处理大文件"""
        with self._pending_lock:
            record = self._pending_files.get(file_id)
            if not record:
                return {"success": False, "error": "待确认文件不存在"}
            record["status"] = "rejected"
            self._pending_files[file_id] = record
            self._save_pending_files()
        return {"success": True, "record": record}

    def _save_to_file(self, group_id: int, message: Dict[str, Any]) -> None:
        """将消息写入JSON文件"""
        today = self._message_date(message)
        group_dir = os.path.join(self.data_dir, str(group_id))
        images_dir = os.path.join(group_dir, "附件", "图片", today)
        os.makedirs(group_dir, exist_ok=True)
        os.makedirs(images_dir, exist_ok=True)

        file_path = os.path.join(group_dir, f"{today}.jsonl")

        with self._file_lock:
            try:
                with open(file_path, 'a', encoding='utf-8') as f:
                    # 去掉raw字段以节省空间
                    save_data = {k: v for k, v in message.items() if k != "raw"}
                    # 精简segments但保留关键内容
                    if "content" in save_data and "segments" in save_data["content"]:
                        simplified_segments = []
                        image_index = 0
                        attachment_index = 0
                        for seg in save_data["content"]["segments"]:
                            seg_entry = {
                                "type": seg["type"],
                                "summary": seg["data"].get("summary", seg["type"])
                            }
                            # 保留文字内容
                            if seg["type"] == "text":
                                seg_entry["text"] = seg["data"].get("text", "")
                            # 保留图片URL
                            elif seg["type"] == "image":
                                image_index += 1
                                img_url = seg["data"].get("url", "")
                                seg_entry["url"] = img_url
                                # 下载图片到本地
                                if self.save_images:
                                    local_path = self._download_image(
                                        img_url, images_dir, message, image_index
                                    )
                                    if local_path:
                                        seg_entry["local_path"] = local_path
                            elif seg["type"] in ("file", "video", "voice"):
                                attachment_index += 1
                                seg_data = seg.get("data", {})
                                seg_entry.update({
                                    "url": seg_data.get("url", ""),
                                    "file": seg_data.get("file", ""),
                                    "name": seg_data.get("name", seg_data.get("file", seg["type"])),
                                    "size": self._parse_size(seg_data.get("size", 0))
                                })
                                if self.save_files:
                                    result = self._save_attachment(seg["type"], seg_data, message, attachment_index)
                                    if result.get("local_path"):
                                        seg_entry["local_path"] = result["local_path"]
                                    if result.get("pending_file_id"):
                                        seg_entry["pending_file_id"] = result["pending_file_id"]
                                        seg_entry["pending_status"] = "waiting_confirm"
                            # 保留表情ID
                            elif seg["type"] == "face":
                                seg_entry["id"] = seg["data"].get("id", "")
                            # 保留回复内容
                            elif seg["type"] == "reply":
                                seg_entry["msg_preview"] = seg["data"].get("msg_preview", "")[:100]
                            # 保留@信息
                            elif seg["type"] == "at":
                                seg_entry["qq"] = seg["data"].get("qq", "")
                                seg_entry["name"] = seg["data"].get("name", "")
                            simplified_segments.append(seg_entry)
                        save_data["content"]["segments"] = simplified_segments

                    f.write(json.dumps(save_data, ensure_ascii=False) + "\n")
            except Exception as e:
                logger.error(f"写入消息文件失败 (群{group_id}): {e}")

    def _download_image(self, url: str, save_dir: str,
                        message: Dict[str, Any], image_index: int = 1) -> Optional[str]:
        """下载图片到本地"""
        if not url:
            return None
        try:
            # 生成文件名
            ext = ".jpg"
            if "gif" in url.lower():
                ext = ".gif"
            elif "png" in url.lower():
                ext = ".png"
            url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
            group_dir = os.path.dirname(os.path.dirname(os.path.dirname(save_dir)))
            existing_path = self._find_existing_image(group_dir, url_hash)
            if existing_path:
                return f"/api/images/{os.path.relpath(existing_path, self.data_dir).replace(os.sep, '/')}"

            filename = self._build_image_filename(message, image_index, url_hash, ext)
            local_path = os.path.join(save_dir, filename)

            # 同一个图片URL只保存一份，重复消息直接指向同一个缓存文件
            if os.path.exists(local_path):
                return f"/api/images/{os.path.relpath(local_path, self.data_dir).replace(os.sep, '/')}"

            max_bytes = max(1, self.max_image_size_mb) * 1024 * 1024
            resp = requests.get(url, timeout=10, stream=True)
            if resp.status_code == 200:
                content_length = resp.headers.get("Content-Length")
                if content_length and int(content_length) > max_bytes:
                    logger.info(f"图片超过大小限制，跳过保存: {content_length} bytes")
                    return None
                downloaded = 0
                with open(local_path, 'wb') as f:
                    for chunk in resp.iter_content(8192):
                        if not chunk:
                            continue
                        downloaded += len(chunk)
                        if downloaded > max_bytes:
                            f.close()
                            try:
                                os.remove(local_path)
                            except OSError:
                                pass
                            logger.info(f"图片下载超过大小限制，已删除临时文件: {url}")
                            return None
                        f.write(chunk)
                rel = os.path.relpath(local_path, self.data_dir).replace(os.sep, '/')
                logger.debug(f"图片已保存: {local_path}")
                return f"/api/images/{rel}"
            else:
                logger.warning(f"图片下载失败: HTTP {resp.status_code}")
                return None
        except Exception as e:
            logger.debug(f"图片下载异常: {e}")
            return None

    def _save_attachment(self, seg_type: str, seg_data: Dict[str, Any],
                         message: Dict[str, Any], index: int) -> Dict[str, Any]:
        """保存普通附件；超过阈值的大文件转入待确认"""
        url = seg_data.get("url", "")
        name = seg_data.get("name", "") or seg_data.get("file", "") or seg_type
        known_size = self._parse_size(seg_data.get("size", 0))
        remote_size = known_size or self._get_remote_size(url)
        if remote_size and remote_size > self._large_file_threshold_bytes:
            record = self._add_pending_large_file(seg_type, seg_data, message, index, remote_size)
            return {"pending_file_id": record["file_id"]}

        local_path = self._download_attachment(seg_type, seg_data, message, index, force=False)
        return {"local_path": local_path} if local_path else {}

    def _download_attachment_record(self, record: Dict[str, Any], force: bool = False) -> Optional[str]:
        """下载待确认文件记录"""
        return self._download_attachment(
            record.get("segment_type", "file"),
            {
                "url": record.get("url", ""),
                "name": record.get("name", ""),
                "file": record.get("name", ""),
                "size": record.get("size", 0)
            },
            record.get("message", {}),
            record.get("index", 1),
            force=force
        )

    def _download_attachment(self, seg_type: str, seg_data: Dict[str, Any],
                             message: Dict[str, Any], index: int,
                             force: bool = False) -> Optional[str]:
        """下载文件/视频/语音附件"""
        url = seg_data.get("url", "")
        if not url:
            return None
        try:
            date_str = self._message_date(message)
            group_id = message.get("group_id", 0)
            group_dir = os.path.join(self.data_dir, str(group_id))
            category = self._attachment_category(seg_type)
            save_dir = os.path.join(group_dir, "附件", category, date_str)
            os.makedirs(save_dir, exist_ok=True)

            original_name = seg_data.get("name", "") or seg_data.get("file", "") or seg_type
            ext = self._guess_extension(original_name, url, seg_type)
            url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
            existing_path = self._find_existing_attachment(group_dir, category, url_hash)
            if existing_path:
                return f"/api/files/{os.path.relpath(existing_path, self.data_dir).replace(os.sep, '/')}"

            filename = self._build_attachment_filename(message, index, original_name, url_hash, ext)
            local_path = os.path.join(save_dir, filename)
            if os.path.exists(local_path):
                return f"/api/files/{os.path.relpath(local_path, self.data_dir).replace(os.sep, '/')}"

            max_bytes = None if force else self._large_file_threshold_bytes
            resp = requests.get(url, timeout=15, stream=True)
            if resp.status_code != 200:
                logger.warning(f"附件下载失败: HTTP {resp.status_code}")
                return None
            content_length = self._parse_size(resp.headers.get("Content-Length", 0))
            if max_bytes and content_length and content_length > max_bytes:
                self._add_pending_large_file(seg_type, seg_data, message, index, content_length)
                return None

            downloaded = 0
            with open(local_path, "wb") as f:
                for chunk in resp.iter_content(1024 * 1024):
                    if not chunk:
                        continue
                    downloaded += len(chunk)
                    if max_bytes and downloaded > max_bytes:
                        f.close()
                        try:
                            os.remove(local_path)
                        except OSError:
                            pass
                        self._add_pending_large_file(seg_type, seg_data, message, index, downloaded)
                        return None
                    f.write(chunk)
            rel = os.path.relpath(local_path, self.data_dir).replace(os.sep, "/")
            return f"/api/files/{rel}"
        except Exception as e:
            logger.debug(f"附件下载异常: {e}")
            return None

    def _add_pending_large_file(self, seg_type: str, seg_data: Dict[str, Any],
                                message: Dict[str, Any], index: int,
                                size: int) -> Dict[str, Any]:
        """新增大文件待确认记录"""
        url = seg_data.get("url", "")
        name = seg_data.get("name", "") or seg_data.get("file", "") or seg_type
        stable_key = f"{message.get('message_id', 0)}:{index}:{url or name}"
        file_id = hashlib.sha1(stable_key.encode("utf-8")).hexdigest()[:10]
        with self._pending_lock:
            if file_id in self._pending_files:
                return self._pending_files[file_id]
            record = {
                "file_id": file_id,
                "status": "waiting_confirm",
                "segment_type": seg_type,
                "name": name,
                "url": url,
                "size": size,
                "size_text": self._format_size(size),
                "index": index,
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "message": {k: v for k, v in message.items() if k != "raw"}
            }
            self._pending_files[file_id] = record
            self._save_pending_files()
        for callback in self._large_file_callbacks:
            try:
                callback(record)
            except Exception as e:
                logger.error(f"大文件待确认回调失败: {e}")
        return record

    def _message_date(self, message: Dict[str, Any]) -> str:
        """获取消息日期"""
        dt = message.get("datetime", "")
        if len(dt) >= 10:
            return dt[:10]
        return datetime.now().strftime("%Y-%m-%d")

    def _safe_filename_part(self, value: Any, max_len: int = 24) -> str:
        """清理文件名片段"""
        text = str(value or "").strip()
        text = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", text)
        text = re.sub(r"\s+", "_", text)
        text = text.strip("._ ")
        return (text[:max_len] or "未知")

    def _build_image_filename(self, message: Dict[str, Any], image_index: int,
                              url_hash: str, ext: str) -> str:
        """生成易读且可去重的图片文件名"""
        dt = message.get("datetime", "")
        date_part = self._message_date(message).replace("-", "")
        time_part = "000000"
        if len(dt) >= 19:
            time_part = dt[11:19].replace(":", "")
        user_id = self._safe_filename_part(message.get("user_id", 0), 20)
        nickname = self._safe_filename_part(message.get("card") or message.get("nickname", "未知"), 20)
        message_id = self._safe_filename_part(message.get("message_id", 0), 24)
        return f"{date_part}_{time_part}_QQ{user_id}_{nickname}_消息{message_id}_图{image_index}_{url_hash}{ext}"

    def _build_attachment_filename(self, message: Dict[str, Any], index: int,
                                   original_name: str, url_hash: str, ext: str) -> str:
        """生成易读附件文件名"""
        dt = message.get("datetime", "")
        date_part = self._message_date(message).replace("-", "")
        time_part = dt[11:19].replace(":", "") if len(dt) >= 19 else "000000"
        user_id = self._safe_filename_part(message.get("user_id", 0), 20)
        nickname = self._safe_filename_part(message.get("card") or message.get("nickname", "未知"), 20)
        message_id = self._safe_filename_part(message.get("message_id", 0), 24)
        base = self._safe_filename_part(os.path.splitext(original_name or "文件")[0], 36)
        return f"{date_part}_{time_part}_QQ{user_id}_{nickname}_消息{message_id}_文件{index}_{base}_{url_hash}{ext}"

    def _find_existing_image(self, group_dir: str, url_hash: str) -> Optional[str]:
        """查找同一群内已缓存的相同图片"""
        images_root = os.path.join(group_dir, "附件", "图片")
        if not os.path.isdir(images_root):
            return None
        marker = f"_{url_hash}."
        try:
            for dirpath, _, filenames in os.walk(images_root):
                for filename in filenames:
                    if marker in filename:
                        return os.path.join(dirpath, filename)
        except OSError:
            return None
        return None

    def _find_existing_attachment(self, group_dir: str, category: str, url_hash: str) -> Optional[str]:
        """查找同一群内已缓存的相同附件"""
        root = os.path.join(group_dir, "附件", category)
        if not os.path.isdir(root):
            return None
        marker = f"_{url_hash}."
        try:
            for dirpath, _, filenames in os.walk(root):
                for filename in filenames:
                    if marker in filename:
                        return os.path.join(dirpath, filename)
        except OSError:
            return None
        return None

    def _attachment_category(self, seg_type: str) -> str:
        """附件分类目录名"""
        return {
            "file": "文件",
            "video": "视频",
            "voice": "语音"
        }.get(seg_type, "文件")

    def _guess_extension(self, name: str, url: str, seg_type: str) -> str:
        """推断附件扩展名"""
        ext = os.path.splitext(name or "")[1]
        if ext and len(ext) <= 12:
            return ext
        url_ext = os.path.splitext(url.split("?")[0])[1]
        if url_ext and len(url_ext) <= 12:
            return url_ext
        return {"video": ".mp4", "voice": ".amr", "file": ".bin"}.get(seg_type, ".bin")

    def _parse_size(self, value: Any) -> int:
        """解析大小字段为字节"""
        try:
            if value is None or value == "":
                return 0
            return int(float(value))
        except (ValueError, TypeError):
            return 0

    def _format_size(self, size: int) -> str:
        """格式化文件大小"""
        size = self._parse_size(size)
        units = ["B", "KB", "MB", "GB", "TB"]
        value = float(size)
        for unit in units:
            if value < 1024 or unit == units[-1]:
                return f"{value:.2f} {unit}" if unit != "B" else f"{int(value)} B"
            value /= 1024

    def _get_remote_size(self, url: str) -> int:
        """通过HEAD获取远程文件大小"""
        if not url:
            return 0
        try:
            resp = requests.head(url, timeout=10, allow_redirects=True)
            if resp.status_code < 400:
                return self._parse_size(resp.headers.get("Content-Length", 0))
        except Exception:
            return 0
        return 0

    def _add_to_index(self, group_id: int, message: Dict[str, Any]) -> None:
        """将消息添加到内存索引"""
        with self._index_lock:
            self._index[group_id].append(message)
            if len(self._index[group_id]) > self._max_index_per_group:
                self._index[group_id] = self._index[group_id][-self._max_index_per_group:]

    # ==================== 查询接口 ====================

    def query_messages(self, group_id: int = None,
                       user_id: int = None,
                       keyword: str = None,
                       start_time: str = None,
                       end_time: str = None,
                       page: int = 1,
                       page_size: int = 50,
                       include_alerts: bool = False) -> Dict[str, Any]:
        """
        查询聊天记录

        Args:
            group_id: 群号（None表示所有群）
            user_id: 用户QQ号（None表示所有用户）
            keyword: 关键词搜索
            start_time: 开始时间 (YYYY-MM-DD HH:MM:SS)
            end_time: 结束时间
            page: 页码
            page_size: 每页条数
            include_alerts: 是否同时返回告警

        Returns:
            {
                "total": 100,
                "page": 1,
                "page_size": 50,
                "messages": [...],
                "alerts": [...]  # 如果include_alerts为True
            }
        """
        # 先从内存索引中查找
        results = []

        if group_id:
            groups_to_search = [group_id]
        else:
            groups_to_search = list(self._index.keys())

        for gid in groups_to_search:
            messages = self._index.get(gid, [])
            for msg in messages:
                if user_id and msg.get("user_id") != user_id:
                    continue
                if keyword:
                    text = msg.get("content", {}).get("text", "")
                    if keyword.lower() not in text.lower():
                        continue
                if start_time:
                    msg_time = msg.get("datetime", "")
                    if msg_time < start_time:
                        continue
                if end_time:
                    msg_time = msg.get("datetime", "")
                    if msg_time > end_time:
                        continue
                results.append(msg)

        # 按时间倒序
        results.sort(key=lambda x: x.get("time", 0), reverse=True)

        total = len(results)
        start = (page - 1) * page_size
        end = start + page_size
        paged = results[start:end]

        response = {
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size,
            "messages": paged
        }

        if include_alerts:
            with self._alerts_lock:
                response["alerts"] = self._sort_alerts_desc(self._alerts)[0:50]
            self._attach_alerts_to_messages(response["messages"])

        return response

    def _attach_alerts_to_messages(self, messages: List[Dict[str, Any]]) -> None:
        """把违规告警标记附加到聊天记录上"""
        if not messages:
            return

        with self._alerts_lock:
            alerts = self._alerts.copy()

        by_msg_id = {}
        by_fallback = {}
        for alert in alerts:
            msg_id = alert.get("message_id")
            if msg_id:
                by_msg_id.setdefault(msg_id, []).append(alert)
            fallback_key = (
                alert.get("group_id"),
                alert.get("user_id"),
                alert.get("datetime")
            )
            by_fallback.setdefault(fallback_key, []).append(alert)

        for msg in messages:
            msg_alerts = []
            msg_id = msg.get("message_id")
            if msg_id and msg_id in by_msg_id:
                msg_alerts.extend(by_msg_id[msg_id])

            fallback_key = (
                msg.get("group_id"),
                msg.get("user_id"),
                msg.get("datetime")
            )
            for alert in by_fallback.get(fallback_key, []):
                if alert not in msg_alerts:
                    msg_alerts.append(alert)

            if msg_alerts:
                msg["alerts"] = msg_alerts
                msg["has_violation"] = True
                latest = self._sort_alerts_desc(msg_alerts)[0]
                msg["violation_summary"] = {
                    "severity": latest.get("severity", "medium"),
                    "category": latest.get("category", "other"),
                    "category_label": latest.get("category_label", ""),
                    "violation_type": latest.get("violation_type", ""),
                    "secondary_status": latest.get("secondary_status", "not_reviewed"),
                    "secondary_status_label": latest.get("secondary_status_label", "未二次复核"),
                    "should_notify": latest.get("should_notify", True),
                    "notified": latest.get("notified", False)
                }

    def query_from_file(self, group_id: int, date: str,
                        user_id: int = None,
                        keyword: str = None) -> List[Dict]:
        """
        从文件中查询指定日期的聊天记录

        Args:
            group_id: 群号
            date: 日期 (YYYY-MM-DD)
            user_id: 用户QQ号（可选）
            keyword: 关键词（可选）
        """
        file_path = os.path.join(self.data_dir, str(group_id), f"{date}.jsonl")
        if not os.path.exists(file_path):
            # 检查是否有压缩文件
            gz_path = file_path + ".gz"
            if os.path.exists(gz_path):
                return self._read_gzip_file(gz_path, user_id, keyword)
            return []

        results = []
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)
                        if user_id and msg.get("user_id") != user_id:
                            continue
                        if keyword:
                            text = msg.get("content", {}).get("text", "")
                            if keyword.lower() not in text.lower():
                                continue
                        results.append(msg)
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.error(f"读取消息文件失败: {e}")

        return results

    def _read_gzip_file(self, gz_path: str,
                        user_id: int = None,
                        keyword: str = None) -> List[Dict]:
        """读取gzip压缩的消息文件"""
        results = []
        try:
            with gzip.open(gz_path, 'rt', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)
                        if user_id and msg.get("user_id") != user_id:
                            continue
                        if keyword:
                            text = msg.get("content", {}).get("text", "")
                            if keyword.lower() not in text.lower():
                                continue
                        results.append(msg)
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.error(f"读取压缩文件失败: {e}")
        return results

    def get_alerts(self, limit: int = 50,
                   group_id: int = None,
                   severity: str = None,
                   category: str = None,
                   secondary_status: str = None) -> List[Dict]:
        """查询告警记录"""
        with self._alerts_lock:
            alerts = self._alerts.copy()

        if group_id:
            alerts = [a for a in alerts if a.get("group_id") == group_id]
        if severity:
            alerts = [a for a in alerts if a.get("severity") == severity]
        if category:
            alerts = [a for a in alerts if a.get("category") == category]
        if secondary_status:
            alerts = [a for a in alerts if a.get("secondary_status") == secondary_status]

        return self._sort_alerts_desc(alerts)[:limit]

    def _sort_alerts_desc(self, alerts: List[Dict]) -> List[Dict]:
        """按告警时间从新到旧排序"""
        def sort_key(alert: Dict[str, Any]) -> Any:
            return (
                alert.get("review_time")
                or alert.get("time")
                or alert.get("datetime")
                or alert.get("message", {}).get("datetime")
                or ""
            )
        return sorted(alerts, key=sort_key, reverse=True)

    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        stats = {
            "total_groups": 0,
            "total_messages": 0,
            "total_alerts": len(self._alerts),
            "storage_used_mb": 0,
            "groups": {},
            "recent_activity": {}
        }

        # 统计各群消息数
        for gid, messages in self._index.items():
            stats["groups"][str(gid)] = {
                "message_count": len(messages),
                "latest_message": messages[-1].get("datetime", "") if messages else ""
            }
            stats["total_messages"] += len(messages)

        stats["total_groups"] = len(self._index)

        # 计算存储空间
        stats["storage_used_mb"] = self._calculate_storage_size()

        return stats

    def get_available_dates(self, group_id: int) -> List[str]:
        """获取指定群可查询的日期列表"""
        group_dir = os.path.join(self.data_dir, str(group_id))
        if not os.path.exists(group_dir):
            return []

        dates = []
        for filename in os.listdir(group_dir):
            if filename.endswith(".jsonl"):
                dates.append(filename.replace(".jsonl", ""))
            elif filename.endswith(".jsonl.gz"):
                dates.append(filename.replace(".jsonl.gz", ""))

        dates.sort(reverse=True)
        return dates

    def get_monitored_groups(self) -> List[Dict]:
        """获取所有已监控群的基本信息"""
        groups = []
        for gid, messages in self._index.items():
            groups.append({
                "group_id": gid,
                "message_count": len(messages),
                "latest_message": messages[-1].get("datetime", "") if messages else "",
                "available_dates": self.get_available_dates(gid)
            })
        return groups

    # ==================== 空间管理 ====================

    def check_storage(self) -> Dict[str, Any]:
        """检查存储空间使用情况"""
        used_mb = self._calculate_storage_size()
        return {
            "used_mb": round(used_mb, 2),
            "max_mb": self.max_storage_mb,
            "usage_percent": round(used_mb / self.max_storage_mb * 100, 2),
            "needs_cleanup": used_mb > self.max_storage_mb * 0.8
        }

    def cleanup_old_files(self) -> Dict[str, Any]:
        """清理旧文件（压缩超过归档天数的文件，删除更老的文件）"""
        cleanup_result = {
            "compressed": 0,
            "deleted": 0,
            "alerts_compacted": 0,
            "freed_mb": 0
        }

        threshold_date = datetime.now() - timedelta(days=self.archive_days)
        delete_date = datetime.now() - timedelta(days=self.archive_days * 2)

        for group_name in os.listdir(self.data_dir):
            group_path = os.path.join(self.data_dir, group_name)
            if not os.path.isdir(group_path):
                continue

            for filename in os.listdir(group_path):
                if not filename.endswith(".jsonl"):
                    continue

                file_path = os.path.join(group_path, filename)
                # 从文件名中提取日期
                date_str = filename.replace(".jsonl", "")
                try:
                    file_date = datetime.strptime(date_str, "%Y-%m-%d")
                except ValueError:
                    continue

                file_size = os.path.getsize(file_path)

                if file_date < delete_date:
                    # 删除过老的文件
                    os.remove(file_path)
                    cleanup_result["deleted"] += 1
                    cleanup_result["freed_mb"] += file_size / (1024 * 1024)
                    logger.info(f"已删除旧文件: {file_path}")

                elif file_date < threshold_date:
                    # 压缩归档文件
                    gz_path = file_path + ".gz"
                    if not os.path.exists(gz_path):
                        try:
                            with open(file_path, 'rb') as f_in:
                                with gzip.open(gz_path, 'wb') as f_out:
                                    shutil.copyfileobj(f_in, f_out)
                            os.remove(file_path)
                            gz_size = os.path.getsize(gz_path)
                            cleanup_result["compressed"] += 1
                            cleanup_result["freed_mb"] += (file_size - gz_size) / (1024 * 1024)
                            logger.info(f"已压缩归档文件: {file_path}")
                        except Exception as e:
                            logger.error(f"压缩文件失败: {file_path}, 错误: {e}")

            # 删除过老的压缩消息文件
            for filename in os.listdir(group_path):
                if not filename.endswith(".jsonl.gz"):
                    continue
                file_path = os.path.join(group_path, filename)
                date_str = filename.replace(".jsonl.gz", "")
                try:
                    file_date = datetime.strptime(date_str, "%Y-%m-%d")
                except ValueError:
                    continue
                if file_date < delete_date:
                    file_size = os.path.getsize(file_path)
                    os.remove(file_path)
                    cleanup_result["deleted"] += 1
                    cleanup_result["freed_mb"] += file_size / (1024 * 1024)
                    logger.info(f"已删除旧压缩文件: {file_path}")

        cleanup_result["alerts_compacted"] = self._compact_alerts_file()

        cleanup_result["freed_mb"] = round(cleanup_result["freed_mb"], 2)
        logger.info(f"清理完成: 压缩{cleanup_result['compressed']}个文件, "
                    f"删除{cleanup_result['deleted']}个文件, "
                    f"释放{cleanup_result['freed_mb']}MB空间")

        return cleanup_result

    def _compact_alerts_file(self) -> int:
        """压缩告警文件，只保留最近的告警记录"""
        alert_file = os.path.join(self.data_dir, "alerts.jsonl")
        if not os.path.exists(alert_file):
            return 0

        try:
            with self._alerts_lock:
                alerts = self._sort_alerts_desc(self._alerts)[:self.max_alert_records]
                # 写回文件时保持旧到新，方便追加和人工查看
                alerts_to_write = list(reversed(alerts))
                self._alerts = alerts_to_write[-self.max_alert_records:]

            temp_file = alert_file + ".tmp"
            with open(temp_file, "w", encoding="utf-8") as f:
                for alert in alerts_to_write:
                    f.write(json.dumps(alert, ensure_ascii=False) + "\n")
            os.replace(temp_file, alert_file)
            return len(alerts_to_write)
        except Exception as e:
            logger.error(f"压缩告警文件失败: {e}")
            return 0

    def _calculate_path_size(self, path: str) -> int:
        """计算文件或目录大小，单位字节"""
        if os.path.isfile(path):
            try:
                return os.path.getsize(path)
            except OSError:
                return 0
        total = 0
        for dirpath, _, filenames in os.walk(path):
            for filename in filenames:
                file_path = os.path.join(dirpath, filename)
                try:
                    total += os.path.getsize(file_path)
                except (OSError, FileNotFoundError):
                    continue
        return total

    def _calculate_storage_size(self) -> float:
        """计算数据目录的总大小(MB)"""
        return self._calculate_path_size(self.data_dir) / (1024 * 1024)

    def flush(self) -> None:
        """刷新所有缓冲数据到磁盘"""
        with self._file_lock:
            self._file_handles.clear()
        logger.info("存储缓冲区已刷新")
