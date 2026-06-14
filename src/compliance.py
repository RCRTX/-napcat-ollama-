"""
AI合规审查模块
使用本地Ollama（OpenAI兼容API）对聊天记录进行合规性审查
"""

import json
import os
import re
import time
import threading
from datetime import datetime
from typing import Dict, Any, List, Optional, Callable

from openai import OpenAI

from .logger import setup_logger

logger = setup_logger("ai_review")


class ViolationDetector:
    """基于关键词的违规检测器"""

    def __init__(self, keywords_file: str, banned_words_file: str,
                 whitelist_users: List[int] = None):
        self.keywords_file = keywords_file
        self.banned_words_file = banned_words_file
        self.whitelist_users = set(whitelist_users or [])

        self._keywords: List[str] = []
        self._keyword_patterns: List[re.Pattern] = []
        self._banned_words: List[str] = []

        self._load_rules()

    def _load_rules(self) -> None:
        """加载关键词和禁言词规则"""
        self._keywords = []
        self._keyword_patterns = []
        self._banned_words = []

        # 加载关键词
        if os.path.exists(self.keywords_file):
            with open(self.keywords_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    # 支持 //包裹的正则表达式
                    if line.startswith("/") and line.endswith("/"):
                        pattern = line[1:-1]
                        try:
                            self._keyword_patterns.append(re.compile(pattern, re.IGNORECASE))
                        except re.error:
                            logger.warning(f"无效的正则表达式: {line}")
                    else:
                        self._keywords.append(line.lower())

        # 加载禁言词
        if os.path.exists(self.banned_words_file):
            with open(self.banned_words_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    self._banned_words.append(line.lower())

        logger.info(f"已加载 {len(self._keywords)} 个关键词, "
                    f"{len(self._keyword_patterns)} 个正则规则, "
                    f"{len(self._banned_words)} 个禁言词")

    def reload_rules(self) -> None:
        """重新加载规则文件"""
        self._load_rules()
        logger.info("规则文件已重新加载")

    def check_message(self, message: Dict[str, Any]) -> Optional[Dict]:
        """
        检查单条消息是否违规

        Returns:
            如果违规返回违规信息字典，否则返回None
        """
        user_id = message.get("user_id", 0)
        if user_id in self.whitelist_users:
            return None

        text = message.get("content", {}).get("text", "").lower()

        # 检查禁言词（严重违规）
        for word in self._banned_words:
            if word in text:
                return {
                    "type": "keyword_violation",
                    "severity": "high",
                    "rule_type": "banned_word",
                    "matched_word": word,
                    "message": message
                }

        # 检查关键词
        for keyword in self._keywords:
            if keyword in text:
                return {
                    "type": "keyword_violation",
                    "severity": "medium",
                    "rule_type": "keyword",
                    "matched_word": keyword,
                    "message": message
                }

        # 检查正则规则
        for pattern in self._keyword_patterns:
            match = pattern.search(text)
            if match:
                return {
                    "type": "keyword_violation",
                    "severity": "medium",
                    "rule_type": "regex",
                    "matched_word": match.group(),
                    "message": message
                }

        return None

    def check_messages_batch(self, messages: List[Dict]) -> List[Dict]:
        """批量检查消息"""
        violations = []
        for msg in messages:
            result = self.check_message(msg)
            if result:
                violations.append(result)
        return violations


class AIReviewer:
    """AI合规审查器，支持本地Ollama和云端API（OpenAI兼容）"""

    def __init__(self, api_base: str, api_key: str, model: str,
                 system_prompt: str, max_messages_per_review: int = 100):
        self.api_base = api_base
        self.api_key = api_key
        self.model = model
        self.system_prompt = system_prompt
        self.max_messages_per_review = max_messages_per_review
        self._last_review_time = 0
        self._is_reviewing = False
        self._last_error = ""
        self._last_result = {
            "review_time": "",
            "reviewed_count": 0,
            "violation_count": 0,
            "error": ""
        }

        self._client = None
        self._init_client()

    def _init_client(self) -> None:
        """初始化OpenAI客户端"""
        try:
            self._client = OpenAI(
                base_url=self.api_base,
                api_key=self.api_key,
                timeout=60
            )
            logger.info(f"AI客户端初始化: base={self.api_base}, model={self.model}")
        except Exception as e:
            logger.error(f"AI客户端初始化失败: {e}")
            self._client = None

    def reload_config(self, api_base: str = None, api_key: str = None,
                      model: str = None, system_prompt: str = None) -> bool:
        """动态重新加载配置"""
        changed = False
        if api_base is not None and api_base != self.api_base:
            self.api_base = api_base
            changed = True
        if api_key is not None and api_key != self.api_key:
            self.api_key = api_key
            changed = True
        if model is not None and model != self.model:
            self.model = model
            changed = True
        if system_prompt is not None and system_prompt != self.system_prompt:
            self.system_prompt = system_prompt
            changed = True

        if changed:
            self._init_client()
            logger.info(f"AI配置已更新: base={self.api_base}, model={self.model}")
        return changed

    def test_connection(self) -> Dict[str, Any]:
        """测试AI连接是否正常"""
        result = {"success": False, "error": "", "model": self.model, "base": self.api_base}
        if not self._client:
            result["error"] = "客户端未初始化"
            return result
        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": "你好，请回复\"连接成功\""}],
                temperature=0.3,
                max_tokens=50
            )
            answer = resp.choices[0].message.content.strip()
            result["success"] = True
            result["response"] = answer
        except Exception as e:
            result["error"] = str(e)
        return result

    def review_messages(self, messages: List[Dict[str, Any]]) -> List[Dict]:
        """
        使用AI审查一批聊天记录

        Returns:
            违规消息列表
        """
        if not messages:
            return []

        self._last_error = ""

        if not self._client:
            self._last_error = "AI客户端未初始化"
            logger.error(f"AI审查失败: {self._last_error}")
            return []

        if self._is_reviewing:
            self._last_error = "AI审查正在进行中"
            logger.info("AI审查正在进行中，跳过本次审查")
            return []

        self._is_reviewing = True
        violations = []

        try:
            # 构建审查文本
            review_text = self._build_review_text(messages)

            # 调用AI
            prompt = f"""{self.system_prompt}

请审查以下QQ群聊记录，判断是否存在违规内容。

## 聊天记录
{review_text}

## 输出要求
请严格按以下JSON格式输出（不要输出其他内容）：
message_index 必须填写聊天记录方括号中的数字，数字从0开始。
```json
{{
    "has_violation": true/false,
    "violations": [
        {{
            "message_index": 0,
            "severity": "low/medium/high/critical",
            "type": "违规类型（如：色情/暴力/广告/人身攻击/政治敏感/其他）",
            "reason": "判定理由",
            "content_preview": "违规内容摘要"
        }}
    ],
    "summary": "整体审查总结"
}}
```"""

            logger.info(f"开始AI审查，共 {len(messages)} 条消息")

            response = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=2000
            )

            result_text = response.choices[0].message.content.strip()
            violations = self._parse_ai_response(result_text, messages)

            self._last_review_time = time.time()
            self._last_result = {
                "review_time": datetime.now().isoformat(),
                "reviewed_count": len(messages),
                "violation_count": len(violations),
                "error": ""
            }
            logger.info(f"AI审查完成，发现 {len(violations)} 条违规")

        except Exception as e:
            self._last_error = str(e)
            self._last_result = {
                "review_time": datetime.now().isoformat(),
                "reviewed_count": len(messages),
                "violation_count": 0,
                "error": self._last_error
            }
            logger.error(f"AI审查失败: {e}")
        finally:
            self._is_reviewing = False

        return violations

    def _build_review_text(self, messages: List[Dict]) -> str:
        """构建发送给AI的审查文本"""
        lines = []
        for i, msg in enumerate(messages):
            if msg.get("type") != "message":
                continue

            sender = msg.get("card") or msg.get("nickname", "未知用户")
            time_str = msg.get("datetime", "")
            content = msg.get("content", {})
            text = content.get("text", "")

            # 附加媒体信息
            media_tags = []
            if content.get("has_image"):
                media_tags.append(f"[图片x{len(content.get('image_urls', []))}]")
            if content.get("has_face"):
                media_tags.append("[表情]")

            media_info = " ".join(media_tags)
            line = f"[{i}] {time_str} {sender}: {text}"
            if media_info:
                line += f" {media_info}"

            lines.append(line)

        return "\n".join(lines)

    def _parse_ai_response(self, response_text: str,
                           original_messages: List[Dict]) -> List[Dict]:
        """解析AI的审查结果"""
        violations = []

        try:
            # 提取JSON部分
            json_match = re.search(r'```json\s*(.*?)\s*```', response_text, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                # 尝试直接解析
                json_str = response_text

            result = json.loads(json_str)

            if not result.get("has_violation", False):
                return []

            for v in result.get("violations", []):
                idx = v.get("message_index", 0)
                if 0 <= idx < len(original_messages):
                    original_msg = original_messages[idx]
                elif 1 <= idx <= len(original_messages):
                    original_msg = original_messages[idx - 1]
                else:
                    original_msg = {}

                violations.append({
                    "type": "ai_violation",
                    "severity": v.get("severity", "medium"),
                    "violation_type": v.get("type", "未知"),
                    "reason": v.get("reason", ""),
                    "content_preview": v.get("content_preview", ""),
                    "message": original_msg,
                    "ai_summary": result.get("summary", ""),
                    "review_time": datetime.now().isoformat()
                })

        except json.JSONDecodeError as e:
            logger.error(f"解析AI响应JSON失败: {e}")
            logger.debug(f"AI原始响应: {response_text[:500]}")
        except Exception as e:
            logger.error(f"处理AI响应失败: {e}")

        return violations

    def get_status(self) -> Dict[str, Any]:
        """获取AI审查器状态"""
        return {
            "is_reviewing": self._is_reviewing,
            "last_error": self._last_error,
            "last_result": self._last_result,
            "last_review_time": self._last_review_time,
            "model": self.model,
            "api_base": self.api_base
        }


class ComplianceManager:
    """合规管理器，整合关键词检测和AI审查"""

    def __init__(self, config: Dict[str, Any], config_path: str = ""):
        self._config = config
        if config_path:
            self._config['_config_path'] = config_path

        rules_config = config.get("rules", {})
        ai_config = config.get("ai_review", {})

        # 初始化关键词检测器
        self.detector = ViolationDetector(
            keywords_file=rules_config.get("keywords_file", "./rules/keywords.txt"),
            banned_words_file=rules_config.get("banned_words_file", "./rules/banned_words.txt"),
            whitelist_users=rules_config.get("whitelist_users", [])
        )

        # 初始化AI审查器
        self.ai_reviewer = None
        if ai_config.get("enabled", False):
            try:
                self.ai_reviewer = AIReviewer(
                    api_base=ai_config.get("api_base", "http://localhost:11434/v1"),
                    api_key=ai_config.get("api_key", "ollama"),
                    model=ai_config.get("model", "qwen2.5"),
                    system_prompt=ai_config.get("system_prompt", ""),
                    max_messages_per_review=ai_config.get("max_messages_per_review", 100)
                )
                logger.info("AI审查器初始化成功")
            except Exception as e:
                logger.error(f"AI审查器初始化失败: {e}")

        self.review_interval = ai_config.get("review_interval_minutes", 5)
        self.max_messages_per_review = ai_config.get("max_messages_per_review", 100)
        self.alert_cooldown = rules_config.get("alert_cooldown_seconds", 300)

        # 待审查消息缓冲区
        self._pending_messages: List[Dict] = []
        self._pending_lock = threading.Lock()

        # 告警冷却记录
        self._alert_cooldowns: Dict[str, float] = {}

        # 违规回调
        self._violation_callbacks: List[Callable] = []

    def on_violation(self, callback: Callable) -> None:
        """注册违规回调"""
        self._violation_callbacks.append(callback)

    def add_message(self, message: Dict[str, Any]) -> Optional[Dict]:
        """
        添加消息进行实时关键词检测

        Returns:
            如果检测到违规返回违规信息，否则返回None
        """
        if message.get("type") != "message":
            return None

        # 实时关键词检测
        violation = self.detector.check_message(message)
        if violation:
            # 检查冷却
            cooldown_key = f"{message.get('group_id')}_{message.get('user_id')}"
            if self._check_cooldown(cooldown_key):
                logger.info(f"关键词违规检测命中: {violation.get('matched_word')}")
                self._trigger_violation(violation)
                return violation

        # 加入待审查缓冲区
        with self._pending_lock:
            self._pending_messages.append(message)
            # 限制缓冲区大小
            if len(self._pending_messages) > self.max_messages_per_review * 2:
                self._pending_messages = self._pending_messages[-self.max_messages_per_review:]

        return None

    def do_ai_review(self) -> List[Dict]:
        """执行AI审查"""
        if not self.ai_reviewer:
            logger.info("AI审查器未启用，跳过审查")
            return []

        with self._pending_lock:
            messages = self._pending_messages.copy()

        if not messages:
            logger.info("没有待审查消息，跳过AI审查")
            return []

        violations = self.ai_reviewer.review_messages(messages)

        if self.ai_reviewer._last_error:
            logger.warning(f"AI审查未成功，保留 {len(messages)} 条待审查消息: {self.ai_reviewer._last_error}")
            return []

        with self._pending_lock:
            reviewed_ids = {
                msg.get("message_id")
                for msg in messages
                if msg.get("message_id")
            }
            if reviewed_ids:
                self._pending_messages = [
                    msg for msg in self._pending_messages
                    if msg.get("message_id") not in reviewed_ids
                ]
            else:
                del self._pending_messages[:len(messages)]

        for v in violations:
            self._trigger_violation(v)

        return violations

    def _trigger_violation(self, violation: Dict) -> None:
        """触发违规回调"""
        for callback in self._violation_callbacks:
            try:
                callback(violation)
            except Exception as e:
                logger.error(f"违规回调执行失败: {e}")

    def _check_cooldown(self, key: str) -> bool:
        """检查告警冷却"""
        now = time.time()
        if key in self._alert_cooldowns:
            if now - self._alert_cooldowns[key] < self.alert_cooldown:
                return False
        self._alert_cooldowns[key] = now
        return True

    def get_pending_count(self) -> int:
        """获取待审查消息数"""
        with self._pending_lock:
            return len(self._pending_messages)

    def get_ai_status(self) -> Dict[str, Any]:
        """获取AI审查状态"""
        status = {
            "enabled": bool(self.ai_reviewer),
            "pending_count": self.get_pending_count()
        }
        if self.ai_reviewer:
            status.update(self.ai_reviewer.get_status())
        return status

    def update_ai_config(self, api_base: str = None, api_key: str = None,
                        model: str = None, system_prompt: str = None,
                        enabled: bool = None, review_interval: int = None) -> Dict[str, Any]:
        """更新AI审查配置并保存到文件"""
        result = {"success": False, "message": ""}

        try:
            if enabled is not None:
                self._config['ai_review']['enabled'] = enabled

            if review_interval is not None:
                self._config['ai_review']['review_interval_minutes'] = review_interval
                self.review_interval = review_interval

            ai_cfg = self._config['ai_review']
            if api_base is not None:
                ai_cfg['api_base'] = api_base
            if api_key is not None:
                ai_cfg['api_key'] = api_key
            if model is not None:
                ai_cfg['model'] = model
            if system_prompt is not None:
                ai_cfg['system_prompt'] = system_prompt

            if enabled is False:
                self.ai_reviewer = None
            elif enabled is True and not self.ai_reviewer:
                self.ai_reviewer = AIReviewer(
                    api_base=ai_cfg.get("api_base", "http://localhost:11434/v1"),
                    api_key=ai_cfg.get("api_key", "ollama"),
                    model=ai_cfg.get("model", "qwen2.5"),
                    system_prompt=ai_cfg.get("system_prompt", ""),
                    max_messages_per_review=ai_cfg.get("max_messages_per_review", 100)
                )

            if self.ai_reviewer:
                self.ai_reviewer.reload_config(
                    api_base=api_base,
                    api_key=api_key,
                    model=model,
                    system_prompt=system_prompt
                )

            # 保存到配置文件
            self._save_config()
            result["success"] = True
            result["message"] = "AI配置已更新"

        except Exception as e:
            result["message"] = f"更新失败: {e}"

        return result

    def get_ai_config(self) -> Dict[str, Any]:
        """获取当前AI配置"""
        cfg = self._config.get('ai_review', {})
        return {
            "enabled": cfg.get('enabled', False),
            "api_base": cfg.get('api_base', ''),
            "api_key": cfg.get('api_key', ''),
            "model": cfg.get('model', ''),
            "system_prompt": cfg.get('system_prompt', ''),
            "review_interval_minutes": cfg.get('review_interval_minutes', 5),
            "max_messages_per_review": cfg.get('max_messages_per_review', 100)
        }

    def test_ai_connection(self) -> Dict[str, Any]:
        """测试AI连接"""
        if not self.ai_reviewer:
            return {"success": False, "error": "AI审查器未启用"}
        return self.ai_reviewer.test_connection()

    def _save_config(self) -> None:
        """保存配置到文件"""
        config_path = self._config.get('_config_path', '')
        if not config_path:
            return
        try:
            save_data = {k: v for k, v in self._config.items() if not k.startswith('_')}
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(save_data, f, ensure_ascii=False, indent=4)
            logger.info("配置已保存到文件")
        except Exception as e:
            logger.error(f"保存配置文件失败: {e}")
