"""
告警通知模块
支持邮件通知和微信推送（Server酱、PushPlus）
"""

import smtplib
import time
import threading
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from datetime import datetime
from typing import Dict, Any, List, Optional

import requests

from .logger import setup_logger

logger = setup_logger("alert")


class EmailNotifier:
    """邮件通知器"""

    def __init__(self, smtp_host: str, smtp_port: int,
                 smtp_user: str, smtp_password: str,
                 sender: str, recipients: List[str],
                 use_ssl: bool = True):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_user = smtp_user
        self.smtp_password = smtp_password
        self.sender = sender or smtp_user
        self.recipients = recipients
        self.use_ssl = use_ssl

    def send(self, title: str, content: str, html: bool = False) -> bool:
        """发送邮件"""
        try:
            msg = MIMEMultipart()
            msg["From"] = Header(f"QQ群监控", "utf-8")
            msg["To"] = ", ".join(self.recipients)
            msg["Subject"] = Header(title, "utf-8")

            if html:
                msg.attach(MIMEText(content, "html", "utf-8"))
            else:
                msg.attach(MIMEText(content, "plain", "utf-8"))

            if self.use_ssl:
                server = smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, timeout=15)
            else:
                server = smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=15)
                server.starttls()

            server.login(self.smtp_user, self.smtp_password)
            server.sendmail(self.sender, self.recipients, msg.as_string())
            server.quit()

            logger.info(f"邮件通知已发送: {title}")
            return True

        except smtplib.SMTPAuthenticationError:
            logger.error("邮件发送失败: SMTP认证失败，请检查用户名和密码/授权码")
            return False
        except smtplib.SMTPException as e:
            logger.error(f"邮件发送失败(SMTP错误): {e}")
            return False
        except Exception as e:
            logger.error(f"邮件发送失败: {e}")
            return False


class ServerChanNotifier:
    """Server酱微信推送通知器"""

    def __init__(self, sendkey: str,
                 api_url: str = "https://sctapi.ftqq.com/{sendkey}.send"):
        self.sendkey = sendkey
        self.api_url = api_url.format(sendkey=sendkey)

    def send(self, title: str, content: str) -> bool:
        """发送Server酱推送"""
        if not self.sendkey:
            return False

        try:
            payload = {
                "title": title,
                "desp": content
            }
            resp = requests.post(self.api_url, data=payload, timeout=10)
            result = resp.json()

            if result.get("code") == 0:
                logger.info("Server酱推送已发送")
                return True
            else:
                logger.error(f"Server酱推送失败: {result.get('message', '未知错误')}")
                return False

        except Exception as e:
            logger.error(f"Server酱推送异常: {e}")
            return False


class PushPlusNotifier:
    """PushPlus微信推送通知器"""

    def __init__(self, token: str,
                 api_url: str = "http://www.pushplus.plus/send"):
        self.token = token
        self.api_url = api_url

    def send(self, title: str, content: str, template: str = "html") -> bool:
        """发送PushPlus推送"""
        if not self.token:
            return False

        try:
            payload = {
                "token": self.token,
                "title": title,
                "content": content,
                "template": template
            }
            resp = requests.post(self.api_url, json=payload, timeout=10)
            result = resp.json()

            if result.get("code") == 200:
                logger.info("PushPlus推送已发送")
                return True
            else:
                logger.error(f"PushPlus推送失败: {result.get('msg', '未知错误')}")
                return False

        except Exception as e:
            logger.error(f"PushPlus推送异常: {e}")
            return False


class QQPrivateNotifier:
    """QQ私聊通知器，通过NapCat HTTP API发送"""

    def __init__(self, http_url: str, token: str = "",
                 recipient_user_ids: List[int] = None):
        self.http_url = http_url.rstrip("/")
        self.token = token
        self.recipient_user_ids = [
            int(uid) for uid in (recipient_user_ids or []) if str(uid).strip()
        ]
        self._session = requests.Session()
        if self.token:
            self._session.headers["Authorization"] = f"Bearer {self.token}"

    def send(self, content: str) -> bool:
        """发送QQ私聊通知"""
        if not self.http_url or not self.recipient_user_ids:
            return False

        success = False
        for user_id in self.recipient_user_ids:
            try:
                payload = {
                    "user_id": user_id,
                    "message": content
                }
                resp = self._session.post(
                    f"{self.http_url}/send_private_msg",
                    json=payload,
                    timeout=10
                )
                result = resp.json()
                if result.get("status") == "ok" or result.get("retcode") == 0:
                    logger.info(f"QQ私聊告警已发送: {user_id}")
                    success = True
                else:
                    logger.error(f"QQ私聊告警发送失败: {result}")
            except Exception as e:
                logger.error(f"QQ私聊告警异常({user_id}): {e}")

        return success


class AlertManager:
    """告警管理器，统一管理所有通知渠道"""

    def __init__(self, config: Dict[str, Any]):
        alert_config = config.get("alert", {})
        napcat_config = config.get("napcat", {})

        self.email_notifier: Optional[EmailNotifier] = None
        self.serverchan_notifier: Optional[ServerChanNotifier] = None
        self.pushplus_notifier: Optional[PushPlusNotifier] = None
        self.qq_private_notifier: Optional[QQPrivateNotifier] = None

        # 初始化QQ私聊通知
        qq_cfg = alert_config.get("qq", {})
        if qq_cfg.get("enabled", False):
            self.qq_private_notifier = QQPrivateNotifier(
                http_url=napcat_config.get("http_url", ""),
                token=napcat_config.get("token", ""),
                recipient_user_ids=qq_cfg.get("recipient_user_ids", [])
            )
            if self.qq_private_notifier.recipient_user_ids:
                logger.info("QQ私聊通知已启用")
            else:
                logger.warning("QQ私聊通知已配置启用，但未填写接收QQ号")

        # 初始化邮件通知
        email_cfg = alert_config.get("email", {})
        if email_cfg.get("enabled", False):
            self.email_notifier = EmailNotifier(
                smtp_host=email_cfg.get("smtp_host", "smtp.qq.com"),
                smtp_port=email_cfg.get("smtp_port", 465),
                smtp_user=email_cfg.get("smtp_user", ""),
                smtp_password=email_cfg.get("smtp_password", ""),
                sender=email_cfg.get("sender", ""),
                recipients=email_cfg.get("recipients", []),
                use_ssl=email_cfg.get("use_ssl", True)
            )
            logger.info("邮件通知已启用")

        # 初始化Server酱
        push_cfg = alert_config.get("push", {})
        if push_cfg.get("enabled", False):
            sc_cfg = push_cfg.get("serverchan", {})
            if sc_cfg.get("sendkey"):
                self.serverchan_notifier = ServerChanNotifier(
                    sendkey=sc_cfg.get("sendkey", ""),
                    api_url=sc_cfg.get("api_url", "https://sctapi.ftqq.com/{sendkey}.send")
                )
                logger.info("Server酱推送已启用")

            # 初始化PushPlus
            pp_cfg = push_cfg.get("pushplus", {})
            if pp_cfg.get("token"):
                self.pushplus_notifier = PushPlusNotifier(
                    token=pp_cfg.get("token", ""),
                    api_url=pp_cfg.get("api_url", "http://www.pushplus.plus/send")
                )
                logger.info("PushPlus推送已启用")

        # 统计
        self._stats = {
            "total_alerts": 0,
            "email_sent": 0,
            "qq_sent": 0,
            "push_sent": 0,
            "errors": 0
        }

    def send_violation_alert(self, violation: Dict[str, Any]) -> None:
        """发送违规告警"""
        self._stats["total_alerts"] += 1

        message = violation.get("message", {})
        severity = violation.get("severity", "medium")
        violation_type = violation.get("type", "")
        reason = violation.get("reason", "")
        matched_word = violation.get("matched_word", "")
        content_preview = violation.get("content_preview", "")

        group_id = message.get("group_id", 0)
        user_id = message.get("user_id", 0)
        nickname = message.get("card") or message.get("nickname", "未知")
        msg_time = message.get("datetime", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        msg_text = message.get("content", {}).get("text", "")[:200]

        # 严重程度映射
        severity_map = {
            "low": "🟡 低",
            "medium": "🟠 中",
            "high": "🔴 高",
            "critical": "⛔ 严重"
        }
        severity_display = severity_map.get(severity, "⚪ 未知")

        # 构建通知内容
        title = f"【群聊违规告警】{severity_display} - 群{group_id}"

        text_content = f"""违规告警通知
{'='*40}

严重程度: {severity_display}
违规类型: {violation_type}
群号: {group_id}
用户: {nickname} (QQ: {user_id})
时间: {msg_time}

违规内容:
{content_preview or msg_text or matched_word}

判定理由:
{reason}

请及时处理！
时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""

        qq_content = f"""【QQ群聊违规告警】
严重程度：{severity_display}
违规类型：{violation_type}
群号：{group_id}
用户：{nickname}（QQ:{user_id}）
消息时间：{msg_time}

违规内容：
{content_preview or msg_text or matched_word}

判定理由：
{reason}

告警时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""

        html_content = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: 'Microsoft YaHei', sans-serif; padding: 20px;">
<div style="max-width: 600px; margin: 0 auto; border: 1px solid #ddd; border-radius: 8px; overflow: hidden;">
    <div style="background: {'#ff4444' if severity in ('high','critical') else '#ff8800'}; color: white; padding: 15px 20px;">
        <h2 style="margin: 0;">⚠️ 群聊违规告警</h2>
    </div>
    <div style="padding: 20px;">
        <table style="width: 100%; border-collapse: collapse;">
            <tr><td style="padding: 8px; border-bottom: 1px solid #eee; font-weight: bold; width: 100px;">严重程度</td><td style="padding: 8px; border-bottom: 1px solid #eee;">{severity_display}</td></tr>
            <tr><td style="padding: 8px; border-bottom: 1px solid #eee; font-weight: bold;">违规类型</td><td style="padding: 8px; border-bottom: 1px solid #eee;">{violation_type}</td></tr>
            <tr><td style="padding: 8px; border-bottom: 1px solid #eee; font-weight: bold;">群号</td><td style="padding: 8px; border-bottom: 1px solid #eee;">{group_id}</td></tr>
            <tr><td style="padding: 8px; border-bottom: 1px solid #eee; font-weight: bold;">用户</td><td style="padding: 8px; border-bottom: 1px solid #eee;">{nickname} (QQ: {user_id})</td></tr>
            <tr><td style="padding: 8px; border-bottom: 1px solid #eee; font-weight: bold;">时间</td><td style="padding: 8px; border-bottom: 1px solid #eee;">{msg_time}</td></tr>
        </table>
        <div style="margin-top: 15px; padding: 12px; background: #fff3f3; border-left: 4px solid #ff4444; border-radius: 4px;">
            <strong>违规内容:</strong><br>{content_preview or msg_text or matched_word}
        </div>
        <div style="margin-top: 10px; padding: 12px; background: #f5f5f5; border-radius: 4px;">
            <strong>判定理由:</strong><br>{reason}
        </div>
    </div>
    <div style="background: #f9f9f9; padding: 10px 20px; color: #999; font-size: 12px; text-align: center;">
        QQ群聊监控系统 · {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    </div>
</div>
</body>
</html>
"""

        # 发送邮件
        if self.email_notifier:
            try:
                if self.email_notifier.send(title, html_content, html=True):
                    self._stats["email_sent"] += 1
                else:
                    self._stats["errors"] += 1
            except Exception as e:
                logger.error(f"邮件发送异常: {e}")
                self._stats["errors"] += 1

        # 发送QQ私聊通知
        if self.qq_private_notifier:
            try:
                if self.qq_private_notifier.send(qq_content):
                    self._stats["qq_sent"] += 1
                else:
                    self._stats["errors"] += 1
            except Exception as e:
                logger.error(f"QQ私聊通知异常: {e}")
                self._stats["errors"] += 1

        # 发送Server酱推送
        if self.serverchan_notifier:
            try:
                if self.serverchan_notifier.send(title, text_content):
                    self._stats["push_sent"] += 1
                else:
                    self._stats["errors"] += 1
            except Exception as e:
                logger.error(f"Server酱推送异常: {e}")
                self._stats["errors"] += 1

        # 发送PushPlus推送
        if self.pushplus_notifier:
            try:
                if self.pushplus_notifier.send(title, html_content, template="html"):
                    self._stats["push_sent"] += 1
                else:
                    self._stats["errors"] += 1
            except Exception as e:
                logger.error(f"PushPlus推送异常: {e}")
                self._stats["errors"] += 1

    def send_test_alert(self) -> bool:
        """发送测试告警"""
        test_violation = {
            "type": "test",
            "severity": "medium",
            "reason": "这是一条测试告警，用于验证通知渠道是否正常",
            "message": {
                "group_id": 000000000,
                "user_id": 000000000,
                "nickname": "测试用户",
                "card": "测试",
                "datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "content": {"text": "这是一条测试消息"}
            }
        }
        self.send_violation_alert(test_violation)
        return True

    def get_stats(self) -> Dict[str, int]:
        """获取告警统计"""
        return self._stats.copy()
