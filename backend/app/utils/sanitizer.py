"""
文本清理和脱敏工具

提供敏感信息检测和脱敏、文本压缩等功能。
"""

import re
from typing import List, Optional, Pattern


# 敏感信息正则表达式模式
SENSITIVE_PATTERNS: dict[str, Pattern] = {
    "email": re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
    "phone": re.compile(r"\b(?:\+?86)?1[3-9]\d{9}\b"),
    "id_card": re.compile(r"\b\d{15}|\d{18}|\d{17}[Xx]\b"),
    "credit_card": re.compile(r"\b(?:4\d{12}(?:\d{3})?|5[1-5]\d{14}|3[47]\d{13})\b"),
    "api_key": re.compile(r"\b(?:sk-|ak-|api[_-]?key[_-]?)[a-zA-Z0-9]{16,}\b", re.IGNORECASE),
    "password": re.compile(r"(?:password|pwd|pass)[\s]*[=:][\s]*[^\s&]+", re.IGNORECASE),
    "secret": re.compile(r"(?:secret|token)[\s]*[=:][\s]*[a-zA-Z0-9]{8,}", re.IGNORECASE),
}


def redact_sensitive_info(
    text: str,
    custom_patterns: Optional[dict[str, str]] = None,
    replacement: str = "[REDACTED]"
) -> str:
    """
    检测并脱敏敏感信息

    Args:
        text: 原始文本
        custom_patterns: 自定义匹配模式 {名称: 正则表达式}
        replacement: 替换字符串

    Returns:
        脱敏后的文本
    """
    if not text:
        return text

    result = text

    # 应用标准脱敏规则
    for name, pattern in SENSITIVE_PATTERNS.items():
        result = pattern.sub(f"[{name.upper()}_REDACTED]", result)

    # 应用自定义模式
    if custom_patterns:
        for name, pattern_str in custom_patterns.items():
            try:
                custom_pattern = re.compile(pattern_str)
                result = custom_pattern.sub(f"[{name.upper()}_REDACTED]", result)
            except re.error:
                # 忽略无效的正则表达式
                continue

    return result


def compact_text(
    text: str,
    max_length: int = 1000,
    preserve_sections: Optional[List[str]] = None,
    remove_empty_lines: bool = True
) -> str:
    """
    压缩文本，移除冗余空白和空行

    Args:
        text: 原始文本
        max_length: 最大长度，超出则截断
        preserve_sections: 需要保留的章节标记
        remove_empty_lines: 是否移除空行

    Returns:
        压缩后的文本
    """
    if not text:
        return text

    result = text

    # 标准化换行符
    result = result.replace("\r\n", "\n").replace("\r", "\n")

    # 移除多余空白
    result = re.sub(r"[ \t]+", " ", result)

    if remove_empty_lines:
        # 移除空行但保留段落结构
        lines = result.split("\n")
        compact_lines = []
        prev_empty = False

        for line in lines:
            stripped = line.strip()
            if not stripped:
                if not prev_empty:
                    compact_lines.append("")
                prev_empty = True
            else:
                compact_lines.append(line)
                prev_empty = False

        result = "\n".join(compact_lines)

    # 截断到最大长度
    if len(result) > max_length:
        # 尝试在句子边界截断
        truncated = result[:max_length]
        last_sentence = max(
            truncated.rfind("."),
            truncated.rfind("。"),
            truncated.rfind("!"),
            truncated.rfind("！"),
            truncated.rfind("?"),
            truncated.rfind("？")
        )
        if last_sentence > max_length * 0.8:
            result = truncated[: last_sentence + 1] + "..."
        else:
            result = truncated + "..."

    return result.strip()


def truncate_text(text: str, max_chars: int = 200, suffix: str = "...") -> str:
    """
    截断文本到指定长度

    Args:
        text: 原始文本
        max_chars: 最大字符数
        suffix: 截断后添加的后缀

    Returns:
        截断后的文本
    """
    if not text or len(text) <= max_chars:
        return text
    return text[:max_chars].strip() + suffix


def remove_html_tags(text: str) -> str:
    """
    移除 HTML 标签

    Args:
        text: 包含 HTML 的文本

    Returns:
        纯文本
    """
    if not text:
        return text
    return re.sub(r"<[^>]+>", "", text)


def sanitize_filename(filename: str, max_length: int = 100) -> str:
    """
    清理文件名，移除不安全字符

    Args:
        filename: 原始文件名
        max_length: 最大长度

    Returns:
        安全的文件名
    """
    if not filename:
        return "unnamed"

    # 移除路径分隔符和控制字符
    sanitized = re.sub(r'[\\/*?:"<>|]', "_", filename)

    # 移除前导和尾随空白/点
    sanitized = sanitized.strip(". ")

    # 限制长度
    if len(sanitized) > max_length:
        name, ext = sanitized.rsplit(".", 1) if "." in sanitized else (sanitized, "")
        sanitized = name[: max_length - len(ext) - 1] + (f".{ext}" if ext else "")

    return sanitized or "unnamed"


def mask_string(text: str, visible_chars: int = 3, mask_char: str = "*") -> str:
    """
    遮盖字符串，只显示开头和结尾的部分字符

    Args:
        text: 原始字符串
        visible_chars: 可见字符数
        mask_char: 遮盖字符

    Returns:
        遮盖后的字符串
    """
    if not text:
        return text
    if len(text) <= visible_chars * 2:
        return mask_char * len(text)

    return text[:visible_chars] + mask_char * (len(text) - visible_chars * 2) + text[-visible_chars:]
