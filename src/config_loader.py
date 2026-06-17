"""
配置加载模块
负责加载和验证配置文件
"""

import json
import os
import copy
from typing import Dict, Any, Optional, List


DEFAULT_CONFIG = {
    "napcat": {
        "ws_url": "ws://localhost:3001",
        "http_url": "http://localhost:3000",
        "token": "",
        "monitor_groups": []
    },
    "storage": {
        "data_dir": "./data",
        "log_dir": "./logs",
        "export_dir": "./聊天记录",
        "max_storage_mb": 500,
        "archive_days": 30,
        "file_rotate_hours": 24,
        "save_images": True,
        "max_image_size_mb": 5,
        "save_files": True,
        "large_file_confirm_mb": 1024,
        "max_alert_records": 1000
    },
    "ai_review": {
        "enabled": True,
        "api_base": "http://localhost:11434/v1",
        "api_key": "ollama",
        "model": "qwen2.5",
        "review_interval_minutes": 5,
        "max_messages_per_review": 100,
        "context_before_messages": 3,
        "context_after_messages": 2,
        "system_prompt": "你是一个严格但不过度误报的QQ群聊内容合规审查专家。请结合上下文判断每条消息是否存在明确风险，不要只因为脏话、玩笑、表情、图片、视频、语音、普通闲聊就判违规。图片、表情、语音、视频等媒体占位本身不是违规证据；除非消息文字明确描述违法、暴力、色情、诈骗等风险，否则不要因为有人发图片或表情而判违规。重点识别：诈骗广告、引流推广、色情低俗、暴力威胁、违法交易、人身攻击、隐私泄露、未成年人风险、政治敏感、赌博博彩、恶意刷屏。判定时必须给出证据片段和理由；证据不足时不要判违规。严重程度规则：critical=违法交易/诈骗/人身安全威胁/严重色情暴力；high=明显违规或强攻击；medium=疑似违规需人工关注；low=轻微不当。必须只输出JSON。"
    },
    "secondary_ai_review": {
        "enabled": True,
        "api_base": "http://localhost:11434/v1",
        "api_key": "ollama",
        "model": "qwen2.5",
        "system_prompt": "你是严格、谨慎、低误报的QQ群聊合规二次复核员。必须只输出JSON。"
    },
    "alert": {
        "qq": {
            "enabled": False,
            "recipient_user_ids": []
        },
        "email": {
            "enabled": False,
            "smtp_host": "smtp.qq.com",
            "smtp_port": 465,
            "smtp_user": "",
            "smtp_password": "",
            "sender": "",
            "recipients": [],
            "use_ssl": True
        },
        "push": {
            "enabled": False,
            "serverchan": {
                "sendkey": "",
                "api_url": "https://sctapi.ftqq.com/{sendkey}.send"
            },
            "pushplus": {
                "token": "",
                "api_url": "http://www.pushplus.plus/send"
            }
        }
    },
    "rules": {
        "keywords_file": "./rules/keywords.txt",
        "banned_words_file": "./rules/banned_words.txt",
        "whitelist_users": [],
        "alert_cooldown_seconds": 300
    }
}


def _deep_merge(base: Dict, override: Dict) -> Dict:
    """深度合并两个字典，override中的值会覆盖base中的值"""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


class Config:
    """全局配置管理器"""

    _instance: Optional['Config'] = None
    _config: Dict[str, Any] = {}

    def __new__(cls, config_path: str = None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, config_path: str = None):
        if not self._config and config_path:
            self.load(config_path)

    def load(self, config_path: str) -> None:
        """从JSON文件加载配置"""
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"配置文件不存在: {config_path}")

        with open(config_path, 'r', encoding='utf-8') as f:
            user_config = json.load(f)

        self._config = _deep_merge(DEFAULT_CONFIG, user_config)
        self._validate()
        self._resolve_paths()

    def load_from_dict(self, config_dict: Dict[str, Any]) -> None:
        """从字典加载配置（用于测试）"""
        self._config = _deep_merge(DEFAULT_CONFIG, config_dict)
        self._validate()
        self._resolve_paths()

    def _validate(self) -> None:
        """验证配置的合法性"""
        # 验证NapCat配置
        if not self._config['napcat']['ws_url']:
            raise ValueError("napcat.ws_url 不能为空")
        if not self._config['napcat']['monitor_groups']:
            raise ValueError("napcat.monitor_groups 不能为空，请至少配置一个群号")

        # 验证存储配置
        if self._config['storage']['max_storage_mb'] < 10:
            raise ValueError("storage.max_storage_mb 不能小于10MB")
        if self._config['storage']['archive_days'] < 1:
            raise ValueError("storage.archive_days 不能小于1天")

        # 验证AI配置
        if self._config['ai_review']['enabled']:
            if not self._config['ai_review']['api_base']:
                raise ValueError("ai_review.api_base 不能为空")
            if not self._config['ai_review']['model']:
                raise ValueError("ai_review.model 不能为空")

        # 验证邮件配置
        email_cfg = self._config['alert']['email']
        if email_cfg['enabled']:
            if not email_cfg['smtp_host']:
                raise ValueError("alert.email.smtp_host 不能为空")
            if not email_cfg['smtp_user']:
                raise ValueError("alert.email.smtp_user 不能为空")
            if not email_cfg['recipients']:
                raise ValueError("alert.email.recipients 不能为空")

    def _resolve_paths(self) -> None:
        """将相对路径解析为绝对路径"""
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self._config['storage']['data_dir'] = os.path.abspath(
            os.path.join(base_dir, self._config['storage']['data_dir'])
        )
        self._config['storage']['log_dir'] = os.path.abspath(
            os.path.join(base_dir, self._config['storage']['log_dir'])
        )
        self._config['storage']['export_dir'] = os.path.abspath(
            os.path.join(base_dir, self._config['storage']['export_dir'])
        )
        self._config['rules']['keywords_file'] = os.path.abspath(
            os.path.join(base_dir, self._config['rules']['keywords_file'])
        )
        self._config['rules']['banned_words_file'] = os.path.abspath(
            os.path.join(base_dir, self._config['rules']['banned_words_file'])
        )

    @property
    def napcat(self) -> Dict[str, Any]:
        return self._config['napcat']

    @property
    def storage(self) -> Dict[str, Any]:
        return self._config['storage']

    @property
    def ai_review(self) -> Dict[str, Any]:
        return self._config['ai_review']

    @property
    def alert(self) -> Dict[str, Any]:
        return self._config['alert']

    @property
    def rules(self) -> Dict[str, Any]:
        return self._config['rules']

    def get(self, key: str, default=None) -> Any:
        """通过点号路径获取配置值，如 config.get('napcat.ws_url')"""
        keys = key.split('.')
        value = self._config
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        return value

    def reload(self, config_path: str = None) -> None:
        """重新加载配置"""
        if config_path is None:
            config_path = self._config_path
        self._config = {}
        self.load(config_path)

    @classmethod
    def reset(cls):
        """重置单例（用于测试）"""
        cls._instance = None
        cls._config = {}
