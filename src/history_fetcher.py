"""
QQ历史消息拉取模块
通过NapCat HTTP API拉取群聊历史消息
"""

import time
import json
import threading
from datetime import datetime
from typing import Dict, Any, List, Optional

import requests

from .logger import setup_logger

logger = setup_logger("history")


class HistoryFetcher:
    """历史消息拉取器"""

    def __init__(self, http_url: str, token: str = "",
                 monitor_groups: List[int] = None):
        self.http_url = http_url.rstrip("/")
        self.token = token
        self.monitor_groups = list(monitor_groups or [])

        self._session = requests.Session()
        self._session.timeout = 30

        if self.token:
            self._session.headers["Authorization"] = f"Bearer {self.token}"

        self._fetched_seqs: Dict[int, int] = {}  # group_id -> last fetched seq
        self._lock = threading.Lock()

    def fetch_group_history(self, group_id: int,
                            count: int = 20,
                            message_seq: int = 0) -> List[Dict[str, Any]]:
        """
        拉取群历史消息

        Args:
            group_id: 群号
            count: 拉取条数（最大20）
            message_seq: 起始消息seq，0表示最新
        """
        try:
            url = f"{self.http_url}/get_group_msg_history"
            payload = {
                "group_id": group_id,
                "message_seq": message_seq,
                "count": count
            }

            resp = self._session.post(url, json=payload)
            result = resp.json()

            if result.get("status") == "ok" and result.get("data"):
                messages = result["data"].get("messages", [])
                logger.info(f"拉取群 {group_id} 历史消息: {len(messages)} 条")
                return messages
            else:
                logger.warning(f"拉取群 {group_id} 历史消息失败: {result.get('message', '未知错误')}")
                return []

        except Exception as e:
            logger.error(f"拉取历史消息异常: {e}")
            return []

    def fetch_all_history(self, group_id: int,
                          max_count: int = 1000,
                          callback=None) -> int:
        """
        拉取群的所有可用历史消息（从最新往回拉）

        Args:
            group_id: 群号
            max_count: 最大拉取条数
            callback: 每批消息的回调函数

        Returns:
            总共拉取的消息数
        """
        total = 0
        message_seq = 0
        empty_count = 0
        max_empty = 3  # 连续空返回次数

        while total < max_count:
            messages = self.fetch_group_history(
                group_id=group_id,
                count=20,
                message_seq=message_seq
            )

            if not messages:
                empty_count += 1
                if empty_count >= max_empty:
                    logger.info(f"群 {group_id}: 连续{max_empty}次无新消息，停止拉取")
                    break
                time.sleep(0.5)
                continue

            empty_count = 0
            total += len(messages)

            # 获取最早一条消息的seq用于下一页
            earliest_seq = None
            for msg in messages:
                seq = msg.get("message_seq", 0)
                if earliest_seq is None or seq < earliest_seq:
                    earliest_seq = seq

            if callback:
                for msg in messages:
                    try:
                        callback(msg)
                    except Exception as e:
                        logger.error(f"历史消息回调异常: {e}")

            if earliest_seq and earliest_seq == message_seq:
                logger.info(f"群 {group_id}: 已到达最早消息")
                break

            message_seq = earliest_seq
            time.sleep(0.3)  # 避免请求过快

        logger.info(f"群 {group_id}: 历史消息拉取完成，共 {total} 条")
        return total

    def fetch_all_groups_history(self, max_count: int = 1000,
                                 callback=None) -> Dict[int, int]:
        """
        拉取所有监控群的历史消息

        Returns:
            {group_id: 拉取条数}
        """
        results = {}
        for group_id in self.monitor_groups:
            count = self.fetch_all_history(
                group_id=group_id,
                max_count=max_count,
                callback=callback
            )
            results[group_id] = count
        return results
