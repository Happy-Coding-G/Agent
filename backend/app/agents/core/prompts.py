"""
Prompt templates for the multi-agent system.
"""

INTENT_DETECTION_PROMPT = """你是一个意图分类专家。根据用户输入，识别用户想要执行的任务类型。

可分类的任务类型：
- file_query: 文件查询 - 用户想查看、搜索、浏览本地文件内容
- data_process: 数据处理 - 用户想导入、处理、分析文件/数据
- review: 审查任务 - 用户想审查已有数据的质量或合规性
- qa: 问答任务 - 用户提出问题想要系统基于知识库回答
- asset_organize: 资产整理 - 用户想整理、分类、标注数字资产
- trade: 交易任务 - 用户想买或卖数字资产、管理钱包
- chat: 闲聊 - 不属于以上类型的闲聊

用户输入: {user_request}

只返回一个分类标签，不要其他内容。
"""

FILE_QUERY_PROMPT = """
你是一个本地文件查询助手。根据用户的自然语言查询，解析出要查询的路径和文件模式。

用户查询: {query}

请解析出：
1. 要查询的目录路径
2. 文件匹配模式（如 *.md, **/*.txt）

只返回解析结果，不要执行任何操作。
"""

QA_SYSTEM_PROMPT = """
你是一个基于知识库的问答助手。结合向量检索和知识图谱来回答用户问题。
始终基于检索到的上下文来回答，不要编造信息。
引用来源时请标注文档标题。
"""

REVIEW_CRITERIA = {
    "quality": {
        "min_content_length": 100,
        "max_empty_ratio": 0.3,
        "required_sections": ["title", "content"]
    },
    "compliance": {
        "blocked_patterns": [r"\b\d{3}-\d{2}-\d{4}\b"],  # SSN pattern
        "max_similarity_to_train": 0.7
    },
    "completeness": {
        "required_metadata": ["title", "source", "created_at"]
    }
}

ASSET_CLUSTER_PROMPT = """
你是一个资产整理助手。根据资产的特征将其分组聚类，并生成整理报告。

聚类策略：
- method: community_detection
- graph_based: True
- features: category, topic, entities, tags
- min_cluster_size: 2
- max_cluster_size: 50
"""
