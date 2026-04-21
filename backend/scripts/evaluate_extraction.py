"""
PDF 抽取效果评估脚本
评估维度：
1. 内容完整性 - 文字提取率、信息丢失
2. 结构准确性 - 标题层级、段落边界、表格
3. 格式保真度 - 数学公式、引用标注、特殊符号
4. 语义连贯性 - 乱码检测、语义连贯
5. 实用指标 - 处理速度、压缩率
"""

import asyncio
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional
import sys

sys.path.insert(0, str(Path(__file__).parent))

from pypdf import PdfReader


PDF_DIR = Path("../personalbench/数据").resolve()


@dataclass
class EvaluationResult:
    """评估结果"""
    filename: str
    pdf_pages: int
    pdf_size: int
    md_size: int
    md_chars: int

    # 1. 内容完整性
    content_score: float = 0.0
    text_coverage: float = 0.0  # 估算的文字覆盖率
    missing_sections: List[str] = field(default_factory=list)

    # 2. 结构准确性
    structure_score: float = 0.0
    has_abstract: bool = False
    has_references: bool = False
    heading_levels: List[int] = field(default_factory=list)
    table_count: int = 0

    # 3. 格式保真度
    format_score: float = 0.0
    formula_issues: int = 0
    garbled_chars: int = 0
    citation_count: int = 0

    # 4. 语义连贯性
    semantic_score: float = 0.0
    paragraph_count: int = 0
    coherence_issues: List[str] = field(default_factory=list)

    # 5. 实用指标
    compression_ratio: float = 0.0
    chars_per_page: float = 0.0


def detect_garbled_text(text: str) -> tuple[int, List[str]]:
    """检测乱码和异常字符"""
    # 检测异常字符模式
    garbled_patterns = [
        r'[\x00-\x08\x0b-\x0c\x0e-\x1f]',  # 控制字符
        r'[^\x00-\x7F]{3,}',  # 连续的非ASCII字符（可能是乱码）
        r'[A-Za-z]\d+[A-Za-z]\d+',  # 页码/引用混乱模式
    ]

    count = 0
    samples = []

    # 检测孤立的字母/数字（通常是PDF解析错误）
    lines = text.split('\n')
    for i, line in enumerate(lines[:100]):  # 检查前100行
        stripped = line.strip()
        # 检测单行只有一个或几个字符的情况（可能是页眉页脚解析错误）
        if len(stripped) <= 3 and stripped and not stripped.startswith('#'):
            count += 1
            if len(samples) < 5:
                samples.append(f"行{i+1}: '{stripped}'")

    # 检测奇怪的重复模式
    weird_patterns = re.findall(r'([a-zA-Z])\n\1\n\1', text[:5000])
    count += len(weird_patterns)

    return count, samples


def detect_formulas(text: str) -> tuple[int, List[str]]:
    """检测数学公式及其问题"""
    # 检测可能的LaTeX公式残留或公式解析问题
    formula_patterns = [
        r'\\[a-zA-Z]+\{',  # LaTeX命令残留
        r'\$\$.*?\$\$',  # 行间公式
        r'\$.*?\$',  # 行内公式
        r'[a-zA-Z]_\{',  # 下标公式
        r'\^\{',  # 上标公式
        r'\\\\[a-z]+',  # LaTeX换行/命令
    ]

    issues = []
    formula_count = 0

    for pattern in formula_patterns:
        matches = re.findall(pattern, text[:10000])
        formula_count += len(matches)

    # 检测公式解析失败的模式（如 "cid:" 乱码）
    bad_formula = re.findall(r'cid:\d+', text)
    if bad_formula:
        issues.append(f"发现 {len(bad_formula)} 处公式解析错误 (cid:xx)")

    # 检测数学符号乱码
    weird_math = re.findall(r'[\u0000-\u0019]{2,}', text)
    if weird_math:
        issues.append(f"发现 {len(weird_math)} 处异常控制字符")

    return formula_count, issues


def analyze_structure(text: str) -> Dict:
    """分析文档结构"""
    result = {}

    # 检测关键章节
    result['has_abstract'] = bool(re.search(r'(?i)^#?\s*abstract\b', text, re.MULTILINE))
    result['has_references'] = bool(re.search(r'(?i)^#?\s*(references|bibliography)\b', text, re.MULTILINE))
    result['has_introduction'] = bool(re.search(r'(?i)^#?\s*\d*\.?\s*introduction\b', text, re.MULTILINE))
    result['has_conclusion'] = bool(re.search(r'(?i)^#?\s*\d*\.?\s*conclusion', text, re.MULTILINE))

    # 检测标题层级
    headings = re.findall(r'^(#{1,6})\s+', text, re.MULTILINE)
    result['heading_levels'] = [len(h) for h in headings]
    result['heading_count'] = len(headings)

    # 检测表格（Markdown表格格式）
    tables = re.findall(r'\|[-:]+\|', text)
    result['table_count'] = len(tables)

    # 段落统计（按空行分割）
    paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
    result['paragraph_count'] = len(paragraphs)

    # 检测引用标注 [1], [2], etc.
    citations = re.findall(r'\[\d+\]', text)
    result['citation_count'] = len(citations)

    return result


def analyze_semantic_coherence(text: str) -> Dict:
    """分析语义连贯性"""
    issues = []

    # 检测段落断裂（行首小写字母，可能是断行错误）
    lines = text.split('\n')
    broken_paragraphs = 0
    for i, line in enumerate(lines[:-1]):
        if line and line[0].islower() and not line.startswith('#'):
            # 检查前一行是否以连字符结尾（断词）
            if lines[i-1].rstrip().endswith('-'):
                broken_paragraphs += 1

    if broken_paragraphs > 10:
        issues.append(f"可能发现 {broken_paragraphs} 处断词未修复")

    # 检测句子断裂（缺少空格）
    no_space = re.findall(r'[a-z][A-Z]', text[:10000])
    if len(no_space) > 20:
        issues.append(f"发现 {len(no_space)} 处可能的大小写连接（缺少空格）")

    # 检测异常短的行（可能是表格或公式解析问题）
    short_lines = [l for l in lines if 0 < len(l.strip()) < 20]
    if len(short_lines) > 50:
        issues.append(f"发现 {len(short_lines)} 处异常短行")

    return {
        'issues': issues,
        'broken_paragraphs': broken_paragraphs,
        'short_lines': len(short_lines)
    }


def evaluate_document(pdf_path: Path, md_path: Path) -> EvaluationResult:
    """评估单个文档"""
    # 读取PDF信息
    try:
        pdf_reader = PdfReader(str(pdf_path))
        pdf_pages = len(pdf_reader.pages)
    except Exception as e:
        print(f"  警告: 无法读取PDF {pdf_path.name}: {e}")
        pdf_pages = 0

    pdf_size = pdf_path.stat().st_size
    md_size = md_path.stat().st_size
    md_text = md_path.read_text(encoding='utf-8')
    md_chars = len(md_text)

    result = EvaluationResult(
        filename=pdf_path.stem,
        pdf_pages=pdf_pages,
        pdf_size=pdf_size,
        md_size=md_size,
        md_chars=md_chars
    )

    # 1. 内容完整性评估
    # 估算覆盖率 (假设每页PDF平均2500字符)
    expected_chars = pdf_pages * 2500 if pdf_pages > 0 else md_chars
    result.text_coverage = min(100, (md_chars / expected_chars) * 100) if expected_chars > 0 else 0

    # 检测缺失的关键部分
    if not re.search(r'(?i)abstract', md_text[:5000]):
        result.missing_sections.append("Abstract")
    if not re.search(r'(?i)introduction', md_text):
        result.missing_sections.append("Introduction")
    if not re.search(r'(?i)conclusion|related work', md_text):
        result.missing_sections.append("Conclusion/Related Work")

    # 内容完整性评分
    content_score = 100
    if result.missing_sections:
        content_score -= len(result.missing_sections) * 10
    if result.text_coverage < 80:
        content_score -= 10
    result.content_score = max(0, content_score)

    # 2. 结构准确性评估
    struct = analyze_structure(md_text)
    result.has_abstract = struct['has_abstract']
    result.has_references = struct['has_references']
    result.heading_levels = struct['heading_levels']
    result.table_count = struct['table_count']
    result.paragraph_count = struct['paragraph_count']
    result.citation_count = struct['citation_count']

    structure_score = 100
    if not result.has_abstract:
        structure_score -= 15
    if not result.has_references:
        structure_score -= 10
    if struct['heading_count'] < 3:
        structure_score -= 20
    result.structure_score = structure_score

    # 3. 格式保真度评估
    result.garbled_chars, garbled_samples = detect_garbled_text(md_text)
    formula_count, formula_issues = detect_formulas(md_text)
    result.formula_issues = len(formula_issues)

    format_score = 100
    if result.garbled_chars > 20:
        format_score -= min(30, result.garbled_chars / 2)
    if formula_issues:
        format_score -= len(formula_issues) * 10
    result.format_score = max(0, format_score)

    # 4. 语义连贯性评估
    semantic = analyze_semantic_coherence(md_text)
    result.coherence_issues = semantic['issues']

    semantic_score = 100
    if semantic['broken_paragraphs'] > 20:
        semantic_score -= 15
    if semantic['short_lines'] > 100:
        semantic_score -= 10
    result.semantic_score = semantic_score

    # 5. 实用指标
    result.compression_ratio = (md_size / pdf_size) * 100 if pdf_size > 0 else 0
    result.chars_per_page = md_chars / pdf_pages if pdf_pages > 0 else 0

    return result, garbled_samples, formula_issues


def print_report(results: List[EvaluationResult]):
    """打印评估报告"""
    print("\n" + "=" * 100)
    print("PDF 抽取效果评估报告")
    print("=" * 100)

    # 概览表
    print("\n【概览】")
    print(f"{'文件名':<20} {'页数':>6} {'PDF大小':>10} {'MD大小':>10} {'压缩率':>10} {'字符/页':>10}")
    print("-" * 80)
    for r in results:
        print(f"{r.filename:<20} {r.pdf_pages:>6} {r.pdf_size/1024:>9.1f}K {r.md_size/1024:>9.1f}K {r.compression_ratio:>9.1f}% {r.chars_per_page:>10.0f}")

    # 评分汇总
    print("\n【综合评分】")
    print(f"{'文件名':<20} {'内容完整':>10} {'结构准确':>10} {'格式保真':>10} {'语义连贯':>10} {'综合得分':>10}")
    print("-" * 80)
    for r in results:
        avg = (r.content_score + r.structure_score + r.format_score + r.semantic_score) / 4
        print(f"{r.filename:<20} {r.content_score:>10.1f} {r.structure_score:>10.1f} {r.format_score:>10.1f} {r.semantic_score:>10.1f} {avg:>10.1f}")

    avg_scores = {
        'content': sum(r.content_score for r in results) / len(results),
        'structure': sum(r.structure_score for r in results) / len(results),
        'format': sum(r.format_score for r in results) / len(results),
        'semantic': sum(r.semantic_score for r in results) / len(results),
    }
    avg_total = sum(avg_scores.values()) / 4

    print(f"\n{'平均':<20} {avg_scores['content']:>10.1f} {avg_scores['structure']:>10.1f} {avg_scores['format']:>10.1f} {avg_scores['semantic']:>10.1f} {avg_total:>10.1f}")

    return avg_scores, avg_total


def print_detailed_issues(results: List[EvaluationResult], all_garbled: Dict, all_formula: Dict):
    """打印详细问题分析"""
    print("\n" + "=" * 100)
    print("【详细问题分析】")
    print("=" * 100)

    for r in results:
        print(f"\n--- {r.filename} ---")

        # 结构检测
        print(f"  结构: Abstract={'[OK]' if r.has_abstract else '[MISS]'}, References={'[OK]' if r.has_references else '[MISS]'}, 标题层级={len(set(r.heading_levels))}层, 表格≈{r.table_count}个")

        # 缺失章节
        if r.missing_sections:
            print(f"  [WARN] 可能缺失: {', '.join(r.missing_sections)}")

        # 乱码样本
        if r.filename in all_garbled and all_garbled[r.filename]:
            print(f"  [WARN] 乱码样本: {all_garbled[r.filename][:3]}")

        # 公式问题
        if r.filename in all_formula and all_formula[r.filename]:
            for issue in all_formula[r.filename][:2]:
                print(f"  [WARN] {issue}")

        # 连贯性问题
        if r.coherence_issues:
            for issue in r.coherence_issues[:2]:
                print(f"  [WARN] {issue}")


def print_summary(avg_scores: Dict, avg_total: float):
    """打印总结和不足分析"""
    print("\n" + "=" * 100)
    print("【评估总结与不足分析】")
    print("=" * 100)

    print(f"""
一、总体表现
================================================================================
综合得分: {avg_total:.1f}/100

各维度得分:
  1. 内容完整性:   {avg_scores['content']:.1f}/100  [{int(avg_scores['content']/20)}/5]
  2. 结构准确性:   {avg_scores['structure']:.1f}/100  [{int(avg_scores['structure']/20)}/5]
  3. 格式保真度:   {avg_scores['format']:.1f}/100  [{int(avg_scores['format']/20)}/5]
  4. 语义连贯性:   {avg_scores['semantic']:.1f}/100  [{int(avg_scores['semantic']/20)}/5]

二、主要不足
================================================================================
""")

    weaknesses = []

    if avg_scores['content'] < 80:
        weaknesses.append("""
【内容完整性不足】
  • PDF页眉页脚中的信息（会议名称、arXiv编号）被错误解析为正文内容
  • 部分文档缺少明确的章节标题识别
  • 参考文献列表可能不完整""")

    if avg_scores['structure'] < 80:
        weaknesses.append("""
【结构准确性问题】
  • 标题层级识别不准确，一级/二级标题可能混淆
  • Markdown表格识别率低，学术论文中的对比表格多为文本形式保留
  • 缺乏对论文标准结构（Abstract→Introduction→...→References）的显式识别""")

    if avg_scores['format'] < 80:
        weaknesses.append("""
【格式保真度缺陷】
  • 数学公式转换效果差：
    - 复杂LaTeX公式无法正确识别
    - 上标/下标符号丢失或乱码
    - 希腊字母常被替换为近似ASCII字符
  • 特殊符号（如向量符号、数学运算符）识别不完整
  • 引用标注 [1], [2] 等有时与正文粘连""")

    if avg_scores['semantic'] < 80:
        weaknesses.append("""
【语义连贯性问题】
  • PDF解析导致的断词未完全修复（行尾连字符）
  • 段落边界识别不准，有时将多段合并或单段拆分
  • 页眉页脚干扰：页面边缘的页码、会议信息混入正文
  • 图表标题与正文的关系丢失""")

    # 通用弱点
    weaknesses.append("""
【其他问题】
  • 压缩率过高（平均3%-10%）：大量格式信息丢失
  • 无法保留原文档的视觉布局信息
  • 对双栏布局的学术论文处理效果一般
  • 图片和图表内容完全丢失（仅保留标题或说明文字）""")

    for w in weaknesses:
        print(w)

    print("""
三、改进建议
================================================================================
  1. 引入专门的学术论文解析器（如Grobid）处理PDF结构
  2. 对数学公式使用专门的LaTeX识别模型（如pix2tex）
  3. 增加后处理步骤修复断词和段落边界
  4. 使用版面分析模型（LayoutLM）识别文档区域类型
  5. 针对双栏学术论文优化分栏合并策略
""")


async def main():
    pdf_files = sorted(PDF_DIR.glob("*.pdf"))

    # 重定向输出到文件
    output_file = PDF_DIR / "evaluation_report.txt"
    import sys
    original_stdout = sys.stdout
    sys.stdout = open(output_file, 'w', encoding='utf-8')

    print(f"PDF抽取效果评估报告")
    print(f"评估时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"共评估 {len(pdf_files)} 个文档\n")

    results = []
    all_garbled = {}
    all_formula = {}

    for pdf_path in pdf_files:
        md_path = pdf_path.with_suffix(".md")
        if not md_path.exists():
            print(f"跳过 {pdf_path.name} - 未找到对应的 .md 文件")
            continue

        print(f"评估: {pdf_path.name}...")
        result, garbled_samples, formula_issues = evaluate_document(pdf_path, md_path)
        results.append(result)
        all_garbled[result.filename] = garbled_samples
        all_formula[result.filename] = formula_issues
        print(f"  -> 完成 (内容:{result.content_score:.0f} 结构:{result.structure_score:.0f} 格式:{result.format_score:.0f} 语义:{result.semantic_score:.0f})")

    # 打印报告
    avg_scores, avg_total = print_report(results)
    print_detailed_issues(results, all_garbled, all_formula)
    print_summary(avg_scores, avg_total)

    sys.stdout.close()
    sys.stdout = original_stdout
    print(f"评估完成！报告已保存到: {output_file}")


if __name__ == "__main__":
    asyncio.run(main())
