"""
QQ群聊监控系统 - 主程序入口
整合所有模块，提供统一的启动和调度
"""

import os
import sys
import time
import signal
import threading
import schedule
from datetime import datetime

# 将src目录加入路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config_loader import Config
from src.logger import setup_logger
from src.napcat_client import NapCatClient
from src.message_store import MessageStore
from src.compliance import ComplianceManager
from src.alert_manager import AlertManager
from src.web_panel import WebPanel
from src.history_fetcher import HistoryFetcher
from src.human_readable_exporter import HumanReadableExporter

logger = setup_logger("main")


class QQMonitor:
    """QQ群聊监控系统主类"""

    def __init__(self, config_path: str):
        self.config_path = config_path

        # 加载配置
        self.config = Config(config_path)

        # 初始化各模块
        self._init_modules()

        # 运行状态
        self._running = False
        self._scheduler_thread = None

    def _init_modules(self) -> None:
        """初始化所有模块"""
        logger.info("正在初始化模块...")

        # 存储模块
        self.store = MessageStore(
            data_dir=self.config.storage['data_dir'],
            log_dir=self.config.storage['log_dir'],
            max_storage_mb=self.config.storage['max_storage_mb'],
            archive_days=self.config.storage['archive_days'],
            file_rotate_hours=self.config.storage['file_rotate_hours'],
            save_images=self.config.storage.get('save_images', True),
            max_image_size_mb=self.config.storage.get('max_image_size_mb', 5),
            max_alert_records=self.config.storage.get('max_alert_records', 1000)
        )

        # NapCat客户端
        self.napcat = NapCatClient(
            ws_url=self.config.napcat['ws_url'],
            token=self.config.napcat.get('token', ''),
            monitor_groups=self.config.napcat['monitor_groups'],
            http_url=self.config.napcat.get('http_url', '')
        )

        # 合规管理器
        self.compliance = ComplianceManager(self.config._config, config_path=self.config_path)

        # 告警管理器
        self.alert = AlertManager(self.config._config)

        # Web面板
        self.web_panel = WebPanel(
            store=self.store,
            host="0.0.0.0",
            port=8080
        )
        self.web_panel.set_components(
            napcat_client=self.napcat,
            compliance_manager=self.compliance,
            alert_manager=self.alert
        )

        # 注册消息处理回调
        self.napcat.on_message(self._on_message_received)

        # 注册违规回调
        self.compliance.on_violation(self._on_violation_detected)

        # 历史消息拉取器
        self.history_fetcher = None
        http_url = self.config.napcat.get('http_url', '')
        if http_url:
            self.history_fetcher = HistoryFetcher(
                http_url=http_url,
                token=self.config.napcat.get('token', ''),
                monitor_groups=self.config.napcat['monitor_groups']
            )
            logger.info("历史消息拉取器初始化成功")

        # 人类可读导出器
        self.exporter = HumanReadableExporter(
            export_dir=self.config.storage.get('export_dir'),
            max_storage_mb=self.config.storage.get('max_storage_mb', 500)
        )
        self.web_panel.set_components(exporter=self.exporter)
        # 导出已有的历史记录
        logger.info("正在导出历史记录为人类可读格式...")
        self.exporter.export_history_from_store(self.store)

        logger.info("所有模块初始化完成")

    def _on_message_received(self, message: dict) -> None:
        """消息接收回调"""
        # 保存消息
        self.store.save_message(message)

        # 导出为人类可读格式
        self.exporter.export_message(message)

        # 实时合规检测
        violation = self.compliance.add_message(message)
        if violation:
            logger.warning(
                f"检测到违规内容! 群:{message.get('group_id')} "
                f"用户:{message.get('nickname')} "
                f"类型:{violation.get('type')} "
                f"级别:{violation.get('severity')}"
            )

    def _on_violation_detected(self, violation: dict) -> None:
        """违规检测回调"""
        message = violation.get("message", {})

        # 构建告警记录
        alert_record = {
            "type": violation.get("type", "unknown"),
            "severity": violation.get("severity", "medium"),
            "category": violation.get("category", "other"),
            "category_label": violation.get("category_label", ""),
            "violation_type": violation.get("violation_type", violation.get("type", "")),
            "reason": violation.get("reason", ""),
            "secondary_status": violation.get("secondary_status", "not_reviewed"),
            "secondary_status_label": violation.get("secondary_status_label", "未二次复核"),
            "secondary_reason": violation.get("secondary_reason", ""),
            "report_basis": violation.get("report_basis", "primary_review"),
            "report_basis_label": violation.get("report_basis_label", "按首次结果上报"),
            "should_notify": violation.get("should_notify", True),
            "matched_word": violation.get("matched_word", ""),
            "content_preview": violation.get("content_preview", ""),
            "message_id": message.get("message_id", 0),
            "group_id": message.get("group_id", 0),
            "user_id": message.get("user_id", 0),
            "nickname": message.get("nickname", ""),
            "card": message.get("card", ""),
            "datetime": message.get("datetime", ""),
            "time": message.get("time", 0),
            "review_time": datetime.now().isoformat(),
            "notified": False
        }

        # 发送通知
        if alert_record["should_notify"]:
            try:
                self.alert.send_violation_alert(violation)
                alert_record["notified"] = True
            except Exception as e:
                alert_record["notify_error"] = str(e)
                logger.error(f"告警通知发送失败，告警记录仍会保存: {e}")
        else:
            logger.info("二次复核认为可能误报，已记录但不发送通知")

        # 保存告警记录
        self.store.save_alert(alert_record)

    def _run_ai_review_once(self, source: str = "手动") -> list:
        """立即执行一次AI审查"""
        try:
            pending_count = self.compliance.get_pending_count()
            logger.info(f"{source}触发AI审查，待审查消息: {pending_count} 条")
            violations = self.compliance.do_ai_review()
            if violations:
                logger.info(f"{source}AI审查发现 {len(violations)} 条违规")
            else:
                logger.info(f"{source}AI审查完成，未发现违规")
            return violations
        except Exception as e:
            logger.error(f"{source}AI审查任务异常: {e}")
            return []

    def _run_scheduler(self) -> None:
        """运行定时任务调度器"""
        logger.info("定时任务调度器已启动")

        # AI审查任务
        review_interval = self.config.ai_review.get('review_interval_minutes', 5)

        def do_review():
            if not self._running:
                return
            self._run_ai_review_once("定时")

        schedule.every(review_interval).minutes.do(do_review)

        # 存储空间检查（每小时）
        def check_storage():
            if not self._running:
                return
            try:
                storage_info = self.store.check_storage()
                if storage_info.get("needs_cleanup"):
                    logger.info("存储空间不足，开始清理...")
                    result = self.store.cleanup_old_files()
                    logger.info(f"清理完成: {result}")
            except Exception as e:
                logger.error(f"存储检查任务异常: {e}")

        schedule.every().hour.do(check_storage)

        # 存储刷新（每10分钟）
        def flush_storage():
            if not self._running:
                return
            try:
                self.store.flush()
            except Exception as e:
                logger.error(f"存储刷新异常: {e}")

        schedule.every(10).minutes.do(flush_storage)

        # 主循环
        while self._running:
            schedule.run_pending()
            time.sleep(1)

    def start(self) -> None:
        """启动监控系统"""
        logger.info("=" * 50)
        logger.info("QQ群聊监控系统启动中...")
        logger.info("=" * 50)

        self._running = True

        # 启动Web面板（后台线程）
        self.web_panel.start_in_thread()

        # 启动定时任务调度器
        self._scheduler_thread = threading.Thread(
            target=self._run_scheduler,
            daemon=True,
            name="Scheduler"
        )
        self._scheduler_thread.start()

        # 启动NapCat WebSocket连接
        self.napcat.start()

        logger.info("=" * 50)
        logger.info("系统启动完成!")
        logger.info(f"Web面板: http://localhost:8080")
        logger.info(f"监控群组: {self.config.napcat['monitor_groups']}")
        logger.info(f"AI审查间隔: {self.config.ai_review.get('review_interval_minutes', 5)}分钟")
        logger.info("=" * 50)

        # 启动时拉取历史消息
        if self.history_fetcher:
            self._fetch_history_on_startup()

        # 主线程等待
        try:
            while self._running:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("收到中断信号，正在停止...")
            self.stop()

    def _fetch_history_on_startup(self) -> None:
        """启动时在后台线程拉取历史消息"""
        def fetch_task():
            # 等待几秒让系统稳定
            time.sleep(3)
            logger.info("开始拉取历史消息...")

            def on_message(raw_msg):
                """将NapCat API返回的原始消息转换为内部格式并保存"""
                try:
                    parsed = self.napcat._parse_message(raw_msg)
                    msg_id = parsed.get("message_id", 0)
                    with self.store._saved_ids_lock:
                        is_new = not msg_id or msg_id not in self.store._saved_message_ids
                    self.store.save_message(parsed)
                    self.exporter.export_message(parsed)
                    if is_new:
                        self.compliance.add_message(parsed)
                except Exception as e:
                    logger.debug(f"历史消息解析跳过: {e}")

            for group_id in self.config.napcat['monitor_groups']:
                try:
                    count = self.history_fetcher.fetch_all_history(
                        group_id=group_id,
                        max_count=2000,
                        callback=on_message
                    )
                    logger.info(f"群 {group_id} 历史消息拉取完成: {count} 条")
                except Exception as e:
                    logger.error(f"群 {group_id} 历史消息拉取失败: {e}")

            logger.info("所有群历史消息拉取完成")
            if self.compliance.get_pending_count() > 0:
                self._run_ai_review_once("启动历史消息")

        thread = threading.Thread(target=fetch_task, daemon=True, name="HistoryFetcher")
        thread.start()

    def stop(self) -> None:
        """停止监控系统"""
        self._running = False
        logger.info("正在停止监控系统...")

        self.napcat.stop()
        self.store.flush()

        logger.info("监控系统已停止")


def main():
    """主函数入口"""
    import argparse

    parser = argparse.ArgumentParser(description="QQ群聊监控系统")
    parser.add_argument(
        "-c", "--config",
        default="config/config.json",
        help="配置文件路径 (默认: config/config.json)"
    )
    parser.add_argument(
        "--web-port",
        type=int,
        default=8080,
        help="Web面板端口 (默认: 8080)"
    )
    parser.add_argument(
        "--test-alert",
        action="store_true",
        help="发送测试告警"
    )

    args = parser.parse_args()

    # 查找配置文件
    config_path = args.config
    if not os.path.isabs(config_path):
        # 在项目根目录下查找
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_path = os.path.join(base_dir, config_path)

    if not os.path.exists(config_path):
        print(f"错误: 配置文件不存在: {config_path}")
        print(f"请复制 config/config.example.json 为 config/config.json 并修改配置")
        sys.exit(1)

    # 启动监控
    monitor = QQMonitor(config_path)

    if args.web_port != 8080:
        monitor.web_panel.port = args.web_port

    if args.test_alert:
        monitor.alert.send_test_alert()
        print("测试告警已发送")
        sys.exit(0)

    # 注册信号处理
    def signal_handler(sig, frame):
        monitor.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    monitor.start()


if __name__ == "__main__":
    main()
