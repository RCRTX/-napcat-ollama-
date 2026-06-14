"""
日志模块
提供统一的日志记录功能
"""

import os
import sys
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime


def setup_logger(name: str = "qq-monitor", log_dir: str = "./logs",
                 level=logging.DEBUG) -> logging.Logger:
    """初始化并返回日志记录器"""
    os.makedirs(log_dir, exist_ok=True)

    logger = logging.getLogger(name)
    logger.setLevel(level)

    # 避免重复添加handler
    if logger.handlers:
        return logger

    # 控制台输出
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_fmt = logging.Formatter(
        "[%(asctime)s] %(levelname)-8s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    console_handler.setFormatter(console_fmt)
    logger.addHandler(console_handler)

    # 文件输出（按天轮转）
    today = datetime.now().strftime("%Y-%m-%d")
    log_file = os.path.join(log_dir, f"monitor_{today}.log")
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=30,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    file_fmt = logging.Formatter(
        "[%(asctime)s] %(levelname)-8s [%(filename)s:%(lineno)d] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    file_handler.setFormatter(file_fmt)
    logger.addHandler(file_handler)

    return logger
