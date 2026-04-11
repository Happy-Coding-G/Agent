# PDF 处理方案

当前仓库只保留一套 PDF 处理方案，并已接入主数据处理流程。

## 主流程入口

- PDF 转 Markdown 入口: [backend/app/ai/converters.py](backend/app/ai/converters.py)
- 统一 PDF 处理实现: [backend/app/ai/pdf_processing.py](backend/app/ai/pdf_processing.py)
- 数据摄入流程接入点: [backend/app/ai/ingest_pipeline.py](backend/app/ai/ingest_pipeline.py)

## 处理链路

统一方案按以下顺序执行：

1. 使用 `markitdown` 做基础 PDF 提取。
2. 清洗页眉页脚等噪声行。
3. 修复常见断词和连字符换行问题。
4. 规整标题层级为 Markdown 标题。
5. 可选使用 `pdfplumber` 提取表格；不可用时回退到轻量文本识别。
6. 输出标准化 Markdown，交给后续 chunking 和 ingest 流程继续处理。

## 设计原则

- 主流程只认一套 PDF 方案，不再保留根目录下独立的增强处理实现。
- 离线脚本如果需要批量处理 PDF，应复用 `app.ai.converters.convert_pdf_to_markdown`。
- `pdfplumber` 属于可选增强依赖；未安装时不会阻断 PDF 主流程。

## 回退策略

当统一 PDF 管线失败时，摄入流程会回退到 `PyPDFLoader`，保证文档摄入不中断。

## 当前保留的相关脚本

- [backend/extract_pdfs.py](backend/extract_pdfs.py): 批量处理脚本，走统一 PDF 管线。
- [backend/evaluate_extraction.py](backend/evaluate_extraction.py): 结果评估脚本，不参与主流程。