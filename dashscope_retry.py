"""DashScope 网络异常识别与有限重试。"""

from time import sleep

from requests.exceptions import ConnectionError, RequestException, SSLError, Timeout


MAX_NETWORK_ATTEMPTS = 3


def is_retryable_network_error(exc: Exception) -> bool:
    """只重试连接、TLS 和超时异常，不掩盖业务或参数错误。"""
    if isinstance(exc, (ConnectionError, SSLError, Timeout, RequestException)):
        return True
    message = str(exc).lower()
    return any(
        keyword in message
        for keyword in (
            "sslerror",
            "unexpected_eof",
            "connection reset",
            "connection aborted",
            "max retries exceeded",
            "timed out",
        )
    )


def wait_before_retry(attempt: int) -> None:
    sleep(min(attempt, 2))


def network_error_message(exc: Exception) -> str:
    return (
        "DashScope 网络连接暂时中断，请检查代理或网络后重试。"
        f"原始错误：{type(exc).__name__}: {exc}"
    )
