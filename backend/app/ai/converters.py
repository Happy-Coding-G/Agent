"""
文档格式转换器 - 分层转换策略
优先级: 专用工具 > Pandoc > LLM
"""

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# 可用工具标记
_pandoc_available: Optional[bool] = None
_html2text_available: Optional[bool] = None


def _get_pandoc_path() -> str:
    """获取 Pandoc 可执行文件路径"""
    import sys
    import os

    # 尝试直接使用 pandoc 命令
    if shutil.which("pandoc"):
        return "pandoc"

    # 尝试从 conda 环境的 Library/bin 目录查找
    env_path = os.path.join(sys.prefix, "Library", "bin", "pandoc.exe")
    if os.path.exists(env_path):
        return env_path

    # 尝试从系统 PATH 中查找
    for path in os.environ.get("PATH", "").split(os.pathsep):
        pandoc_path = os.path.join(path, "pandoc.exe")
        if os.path.exists(pandoc_path):
            return pandoc_path

    return "pandoc"  # 最后尝试直接调用


def _check_pandoc() -> bool:
    """检查 Pandoc 是否可用"""
    global _pandoc_available
    if _pandoc_available is None:
        try:
            pandoc_cmd = _get_pandoc_path()
            result = subprocess.run(
                [pandoc_cmd, "--version"],
                capture_output=True,
                timeout=5,
            )
            _pandoc_available = result.returncode == 0
            if _pandoc_available:
                logger.info(f"Pandoc is available at: {pandoc_cmd}")
        except Exception:
            _pandoc_available = False
            logger.warning("Pandoc not available, will fall back to LLM conversion")
    return _pandoc_available


def _check_html2text() -> bool:
    """检查 html2text 是否可用"""
    global _html2text_available
    if _html2text_available is None:
        try:
            import html2text
            _html2text_available = True
            logger.info("html2text is available for HTML conversion")
        except ImportError:
            _html2text_available = False
            logger.warning("html2text not available, will use alternative method")
    return _html2text_available


def convert_docx_to_markdown(file_path: Path) -> Optional[str]:
    """
    使用 Pandoc 将 DOCX/DOC 转换为 Markdown
    返回 None 表示失败
    """
    if not _check_pandoc():
        return None

    try:
        pandoc_cmd = _get_pandoc_path()
        result = subprocess.run(
            [pandoc_cmd, str(file_path), "-f", "docx", "-t", "markdown", "--wrap=none"],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        if result.returncode == 0 and result.stdout.strip():
            logger.info(f"Pandoc successfully converted DOCX: {file_path.name}")
            return result.stdout
        else:
            logger.warning(f"Pandoc failed for DOCX: {result.stderr}")
            return None
    except Exception as e:
        logger.warning(f"Pandoc DOCX conversion failed: {e}")
        return None


def convert_rtf_to_markdown(file_path: Path) -> Optional[str]:
    """
    使用 Pandoc 将 RTF 转换为 Markdown
    返回 None 表示失败
    """
    if not _check_pandoc():
        return None

    try:
        pandoc_cmd = _get_pandoc_path()
        result = subprocess.run(
            [pandoc_cmd, str(file_path), "-f", "rtf", "-t", "markdown", "--wrap=none"],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        if result.returncode == 0 and result.stdout.strip():
            logger.info(f"Pandoc successfully converted RTF: {file_path.name}")
            return result.stdout
        else:
            logger.warning(f"Pandoc failed for RTF: {result.stderr}")
            return None
    except Exception as e:
        logger.warning(f"Pandoc RTF conversion failed: {e}")
        return None


def convert_odt_to_markdown(file_path: Path) -> Optional[str]:
    """
    使用 Pandoc 将 ODT 转换为 Markdown
    返回 None 表示失败
    """
    if not _check_pandoc():
        return None

    try:
        pandoc_cmd = _get_pandoc_path()
        result = subprocess.run(
            [pandoc_cmd, str(file_path), "-f", "odt", "-t", "markdown", "--wrap=none"],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        if result.returncode == 0 and result.stdout.strip():
            logger.info(f"Pandoc successfully converted ODT: {file_path.name}")
            return result.stdout
        else:
            logger.warning(f"Pandoc failed for ODT: {result.stderr}")
            return None
    except Exception as e:
        logger.warning(f"Pandoc ODT conversion failed: {e}")
        return None


def convert_html_to_markdown(file_path: Path) -> Optional[str]:
    """
    使用 html2text 将 HTML 转换为 Markdown
    返回 None 表示失败
    """
    if not _check_html2text():
        return None

    try:
        import html2text

        html_content = file_path.read_text(encoding="utf-8", errors="ignore")
        h2t = html2text.HTML2Text()
        h2t.body_width = 0  # 不自动换行
        h2t.ignore_links = False
        h2t.ignore_images = False
        h2t.ignore_emphasis = False

        markdown = h2t.handle(html_content)
        if markdown.strip():
            logger.info(f"html2text successfully converted HTML: {file_path.name}")
            return markdown
        return None
    except Exception as e:
        logger.warning(f"html2text HTML conversion failed: {e}")
        return None


def convert_pdf_to_markdown(file_path: Path) -> Optional[str]:
    """
    使用 markitdown 将 PDF 转换为 Markdown
    返回 None 表示失败

    markitdown 效果优于 pdfminer:
    - 能识别表格并转换为 Markdown 表格格式
    - 能保留代码块的标记
    - 能识别标题层级结构
    - 支持图片 Alt 文字提取
    """
    try:
        from markitdown import MarkItDown

        converter = MarkItDown()
        result = converter.convert(str(file_path))

        if result and result.text_content and result.text_content.strip():
            logger.info(f"markitdown successfully converted PDF: {file_path.name}")
            return result.text_content.strip()
        return None
    except ImportError:
        logger.warning("markitdown not installed, PDF conversion unavailable")
        return None
    except Exception as e:
        logger.warning(f"markitdown PDF conversion failed: {e}")
        return None


def needs_llm_conversion(filename: str, text: str) -> bool:
    """
    判断是否需要 LLM 转换

    条件:
    1. 文件已尝试过专用工具转换但失败
    2. 文本不是 Markdown 格式
    3. 文本是复杂格式（如 OCR 输出、日志、混乱文本）
    """
    suffix = Path(filename).suffix.lower() if filename else ""

    # 这些格式已尝试过专用工具，不应再回退到 LLM
    already_tried_tools = {
        ".docx", ".doc", ".rtf", ".odt",
        ".html", ".htm",
        ".pdf",
        ".md", ".markdown",
        ".txt", ".csv", ".json", ".yaml", ".yml", ".xml",
    }

    if suffix in already_tried_tools:
        # 专用工具已尝试过，如果失败就不应该再试 LLM
        # 除非文本看起来是 OCR 或其他需要语义理解的混乱文本
        return _looks_like_ocr_or_garbled(text)

    # 其他格式需要 LLM 转换
    if not looks_like_markdown_basic(text):
        return True

    return False


def looks_like_markdown_basic(text: str) -> bool:
    """
    简单的 Markdown 格式检测
    只检测明确的 Markdown 标记
    """
    import re

    if not text:
        return False

    patterns = [
        r"(?m)^#{1,6}\s+\S+",           # 标题
        r"(?m)^[-*+]\s+\S+",             # 无序列表
        r"(?m)^\d+\.\s+\S+",             # 有序列表
        r"(?m)^>\s+\S+",                 # 引用
        r"(?m)^```",                     # 代码块
        r"\[[^\]]+\]\([^)]+\)",          # 链接
        r"(?m)^\|.+\|$",                 # 表格
    ]

    hit_count = sum(1 for p in patterns if re.search(p, text))
    return hit_count >= 1


def _looks_like_ocr_or_garbled(text: str) -> bool:
    """
    检测文本是否是 OCR 输出或乱码文本
    这类文本需要 LLM 才能正确转换
    """
    import re

    if not text:
        return False

    # 检查字符分布
    # OCR 或乱码通常有大量异常字符
    unusual_chars = sum(1 for c in text if ord(c) > 127 and not _is_letter_or_cjk(c))
    unusual_ratio = unusual_chars / max(len(text), 1)

    # 超过 20% 异常字符认为是乱码
    if unusual_ratio > 0.2:
        return True

    # 检查是否有过多的连续相似字符（扫描错误特征）
    if re.search(r"(.)\1{10,}", text):  # 10个以上相同字符连续
        return True

    # 检查换行模式 - OCR 可能有大量短行
    lines = text.split("\n")
    if len(lines) > 10:
        short_lines = sum(1 for l in lines if len(l.strip()) < 20)
        if short_lines / len(lines) > 0.7:  # 70% 以上是短行
            return True

    return False


def _is_letter_or_cjk(c: str) -> bool:
    """判断字符是否是字母或中日韩文字"""
    code = ord(c)
    # Basic Latin + CJK Unified Ideographs
    return (0x0041 <= code <= 0x007A) or (0x4E00 <= code <= 0x9FFF) or (0x3040 <= code <= 0x30FF)
