"""
文档转换和评分脚本
用于将测试数据集中的文档转换为Markdown并评估质量
"""
import sys
import json
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.ai.converters import (
    convert_docx_to_markdown,
    convert_pdf_to_markdown,
    looks_like_markdown_basic,
    _check_pandoc,
)
from app.ai.markdown_utils import normalize_markdown
from test_conversion_quality import calculate_overall_score

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def get_test_data_dir() -> Path:
    """获取测试数据目录"""
    return Path(__file__).parent / "data" / "conversion_testset"


def get_output_dir() -> Path:
    """获取输出目录"""
    output = Path(__file__).parent / "data" / "conversion_output"
    output.mkdir(parents=True, exist_ok=True)
    return output


def convert_file(file_path: Path) -> tuple[str, bool]:
    """
    转换单个文件
    返回: (markdown_text, success)
    """
    suffix = file_path.suffix.lower()

    logger.info(f"Converting: {file_path.name} ({suffix})")

    # 已经是 Markdown
    if suffix in {".md", ".markdown", ".mdown"}:
        text = file_path.read_text(encoding="utf-8", errors="ignore")
        return text, True

    # DOCX/DOC
    if suffix in {".docx", ".doc"}:
        if not _check_pandoc():
            logger.warning(f"Pandoc not available for {file_path.name}")
            return "", False
        result = convert_docx_to_markdown(file_path)
        return result if result else "", bool(result)

    # PDF
    if suffix == ".pdf":
        result = convert_pdf_to_markdown(file_path)
        return result if result else "", bool(result)

    # 不支持的格式
    logger.warning(f"Unsupported format: {suffix}")
    return "", False


def process_all_documents():
    """处理所有测试文档"""
    test_data_dir = get_test_data_dir()
    output_dir = get_output_dir()

    # 收集所有待转换文件
    files_to_convert = []

    # 原始数据目录
    original_dir = Path(__file__).parent.parent.parent / "personalbench" / "数据"
    if original_dir.exists():
        for ext in {".pdf", ".docx", ".doc", ".md", ".markdown"}:
            files_to_convert.extend(original_dir.glob(f"*{ext}"))
            files_to_convert.extend(original_dir.glob(f"*{ext.upper()}"))

    # 也检查测试数据目录本身
    for ext in {".pdf", ".docx", ".doc", ".md", ".markdown"}:
        files_to_convert.extend(test_data_dir.glob(f"**/*{ext}"))

    # 去重
    files_to_convert = list(set(files_to_convert))

    logger.info(f"Found {len(files_to_convert)} files to convert")

    results = []

    for file_path in files_to_convert:
        try:
            markdown_text, success = convert_file(file_path)

            if not success or not markdown_text:
                logger.warning(f"Failed to convert: {file_path.name}")
                continue

            # 规范化
            normalized = normalize_markdown(markdown_text)

            # 计算质量得分
            score_result = calculate_overall_score(normalized)

            # 保存转换结果
            output_file = output_dir / f"{file_path.stem}.md"
            output_file.write_text(normalized, encoding="utf-8")

            result = {
                "original_file": str(file_path.name),
                "output_file": str(output_file.name),
                "success": True,
                "score": score_result["overall_score"],
                "grade": score_result["grade"],
                "details": score_result
            }
            results.append(result)

            logger.info(f"✓ {file_path.name} -> {output_file.name} (Score: {score_result['overall_score']}, Grade: {score_result['grade']})")

        except Exception as e:
            logger.error(f"Error converting {file_path.name}: {e}")
            results.append({
                "original_file": str(file_path.name),
                "success": False,
                "error": str(e)
            })

    # 保存结果报告
    report = {
        "total_files": len(files_to_convert),
        "successful": sum(1 for r in results if r.get("success", False)),
        "failed": sum(1 for r in results if not r.get("success", False)),
        "results": results,
        "average_score": sum(r.get("score", 0) for r in results if r.get("success")) / max(len([r for r in results if r.get("success")]), 1)
    }

    report_file = output_dir / "conversion_report.json"
    report_file.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    logger.info(f"\n{'='*60}")
    logger.info(f"Conversion Summary:")
    logger.info(f"  Total files: {report['total_files']}")
    logger.info(f"  Successful: {report['successful']}")
    logger.info(f"  Failed: {report['failed']}")
    logger.info(f"  Average score: {report['average_score']:.3f}")
    logger.info(f"{'='*60}")
    logger.info(f"Report saved to: {report_file}")

    return report


def main():
    """主入口"""
    logger.info("Starting document conversion and quality assessment...")
    logger.info(f"Output directory: {get_output_dir()}")

    # 检查 Pandoc
    if _check_pandoc():
        logger.info("Pandoc is available")
    else:
        logger.warning("Pandoc is NOT available - DOCX conversion will fail")

    report = process_all_documents()

    # 打印结果表格
    print("\n" + "="*80)
    print(f"{'File':<40} {'Score':<10} {'Grade':<6}")
    print("="*80)

    for r in report.get("results", []):
        if r.get("success"):
            print(f"{r['original_file']:<40} {r['score']:<10.3f} {r['grade']:<6}")
        else:
            print(f"{r['original_file']:<40} {'FAILED':<10} {'-':<6}")

    print("="*80)
    print(f"Average Score: {report.get('average_score', 0):.3f}")
    print(f"Total: {report.get('total_files', 0)}, Success: {report.get('successful', 0)}, Failed: {report.get('failed', 0)}")


if __name__ == "__main__":
    main()
