# L2 Ingest Agent 领域规则

## Idempotency

- 同一文件在同一文档下重复上传时，应基于 `content_hash` 判断是否需要重新处理。
- 若 hash 未变，跳过解析、分块、嵌入和图谱构建步骤，直接返回现有文档信息。
- 更新文档内容时，先清理旧的 chunks、embeddings 和图谱节点，再写入新数据。

## 支持文件类型

- 文本类：TXT、Markdown、CSV、JSON
- 办公文档：PDF、DOCX
- 禁止处理可执行文件（EXE、BAT、SH）、压缩包（ZIP、RAR）和未知 MIME 类型。

## 知识图谱构建规范

- 每个文档对应一个图谱子图（graph_id）。
- 实体抽取应聚焦文档中的核心概念、人物、组织、技术术语。
- 关系抽取应基于文档中的显式关联，禁止过度推断。
- 图谱节点和关系必须关联回原始文档的 `doc_id` 和 `chunk` 位置。
