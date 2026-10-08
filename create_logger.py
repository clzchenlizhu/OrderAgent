import logging
import os
from contextvars import ContextVar
import uuid

from config import Config

# 请求ID上下文变量（跨线程/协程传递）
request_id_var: ContextVar[str] = ContextVar('request_id', default='-')


def set_request_id(request_id: str = None):
    """设置当前请求的request_id"""
    if not request_id:
        request_id = str(uuid.uuid4())[:8]
    request_id_var.set(request_id)
    return request_id


def get_request_id() -> str:
    """获取当前请求的request_id"""
    return request_id_var.get()


class RequestIdFilter(logging.Filter):
    """日志过滤器，自动注入request_id"""
    def filter(self, record):
        record.request_id = get_request_id()
        return True


def setup_logger(name, log_file='logs/app.log'):
    # 创建日志文件夹
    os.makedirs(os.path.dirname(log_file), exist_ok=True)

    # 获取日志记录器
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    # 防止重复输出的关键！
    logger.propagate = False

    # 定义日志格式（带request_id）
    formatter = logging.Formatter(
        '%(name)s - %(asctime)s - %(levelname)s - [%(request_id)s] - %(message)s'
    )

    # 添加request_id过滤器
    request_id_filter = RequestIdFilter()

    # 创建控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)
    console_handler.addFilter(request_id_filter)

    # 创建文件处理器
    file_handler = logging.FileHandler(filename=log_file, encoding="utf-8", mode="a")
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)
    file_handler.addFilter(request_id_filter)

    # 将处理器添加到日志记录器中
    if not logger.handlers:
        logger.addHandler(console_handler)
        logger.addHandler(file_handler)

    return logger

logger = setup_logger('SmartVoage', Config().log_file)
