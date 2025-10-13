"""项目内使用的自定义异常定义。"""


class ImageAutomationError(Exception):
    """基础异常类型。"""


class InvalidConfigurationError(ImageAutomationError):
    """配置不合法时抛出。"""


class ProcessingAborted(ImageAutomationError):
    """任务被用户中断时抛出。"""
