"""
Snowflake ID 生成器

生成唯一的分布式 ID，格式参考 Twitter Snowflake 算法。
简化实现：使用 UUID + 时间戳组合。
"""

import time
import uuid
import random

# 起始时间戳 (2024-01-01)
EPOCH = 1704067200000

# 节点 ID (0-31)
_worker_id = random.randint(0, 31)

# 序列号 (0-4095)
_sequence = 0

# 上次生成 ID 的时间戳
_last_timestamp = -1


def _current_timestamp() -> int:
    """获取当前时间戳（毫秒）"""
    return int(time.time() * 1000)


def snowflake_id() -> str:
    """
    生成唯一 Snowflake ID

    Returns:
        字符串形式的唯一 ID，格式：时间戳-随机数
    """
    global _sequence, _last_timestamp

    timestamp = _current_timestamp()

    if timestamp == _last_timestamp:
        # 同一毫秒内，增加序列号
        _sequence = (_sequence + 1) & 4095
        if _sequence == 0:
            # 序列号溢出，等待下一毫秒
            while timestamp <= _last_timestamp:
                timestamp = _current_timestamp()
    else:
        # 不同毫秒，重置序列号
        _sequence = random.randint(0, 100)

    _last_timestamp = timestamp

    # 组合 ID: 时间戳 + 工作节点 + 序列号
    # 格式：timestamp-worker-sequence-random
    unique_id = f"{timestamp - EPOCH:012d}-{_worker_id:02d}-{_sequence:04d}-{random.randint(1000, 9999):04d}"
    return unique_id


def generate_uuid() -> str:
    """
    生成标准 UUID

    Returns:
        字符串形式的 UUID
    """
    return str(uuid.uuid4()).replace("-", "")


def short_id(length: int = 12) -> str:
    """
    生成短 ID

    Args:
        length: ID 长度

    Returns:
        指定长度的随机字符串
    """
    chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    return "".join(random.choices(chars, k=length))
