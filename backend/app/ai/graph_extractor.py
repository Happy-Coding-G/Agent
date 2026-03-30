"""
多步知识图谱抽取模块

实现分步抽取 + 反思迭代策略：
1. 实体抽取 (CNER)
2. 实体属性补全
3. 关系抽取 (RE)
4. 关系属性补全 (qualifiers/attributes/confidence/polarity)
5. 反思迭代补全 (默认2轮，最多5轮)
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from app.core.config import settings

logger = logging.getLogger(__name__)


# ============================================================================
# 数据结构
# ============================================================================


@dataclass
class ExtractedEntity:
    """抽取的实体"""
    name: str
    labels: List[str] = field(default_factory=lambda: ["Entity"])
    description: Optional[str] = None
    attributes: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExtractedRelation:
    """抽取的关系"""
    source: str  # 源实体名
    target: str  # 目标实体名
    name: str  # 关系名 (UPPER_SNAKE_CASE)
    fact: str  # 事实描述
    valid_at: Optional[str] = None  # 生效时间
    invalid_at: Optional[str] = None  # 失效时间
    cardinality: Optional[str] = None  # "one" or "many"
    qualifiers: Dict[str, Any] = field(default_factory=dict)
    attributes: Dict[str, Any] = field(default_factory=dict)
    confidence: Optional[float] = None
    polarity: Optional[int] = None  # 1: positive, -1: negative


@dataclass
class ExtractionResult:
    """抽取结果"""
    entities: List[ExtractedEntity] = field(default_factory=list)
    relations: List[ExtractedRelation] = field(default_factory=list)
    episodes: List[str] = field(default_factory=list)  # 证据片段引用


# ============================================================================
# Prompt 构建函数
# ============================================================================


def build_entity_extraction_prompt(
    current_episode_time: str,
    current_episode_text: str,
    context_block: str = "",
) -> str:
    """
    实体抽取 prompt（仅抽实体，不抽关系）。
    """
    return (
        "你是一个信息抽取助手。请从给定文本中抽取\"实体\"。\n\n"
        "要求：\n"
        "1) 只输出 JSON，不要输出任何额外文本。\n"
        "2) 只抽实体，不要抽关系/边。\n"
        "3) 实体名尽量规范、去噪、去代词；同名合并。\n"
        "4) labels 默认包含 Entity，可追加 Person/Org/Location/Product/Project 等。\n"
        "5) 必须输出 {\"entities\": [...]}，且顶层只允许 entities；无实体则输出 {\"entities\": []}。\n\n"
        f"当前时间：{current_episode_time}\n\n"
        f"上下文：\n{context_block}\n\n"
        f"文本：\n{current_episode_text}\n"
    )


def build_entity_attributes_prompt(
    current_episode_time: str,
    current_episode_text: str,
    entities_json: str,
) -> str:
    """
    实体属性抽取 prompt（在已给定实体集合的基础上补全属性）。
    """
    return (
        "你是一个信息抽取助手。请基于给定文本，为\"已知实体列表\"补充实体属性。\n\n"
        "要求：\n"
        "1) 只输出 JSON，不要输出任何额外文本。\n"
        "2) 只为给定实体补充属性，不要新增实体。\n"
        "3) attributes 必须是对象；缺失则输出空对象 {}。\n"
        "4) 属性请用简洁键名（如 role/title/department/location/id/version/status 等）。\n"
        "5) 必须输出 {\"entities\": [...]}，不要输出以实体名为 key 的字典；无属性也要保留 entities 数组。\n\n"
        f"当前时间：{current_episode_time}\n\n"
        f"已知实体（JSON）：\n{entities_json}\n\n"
        f"文本：\n{current_episode_text}\n"
    )


def build_relation_extraction_prompt(
    current_episode_time: str,
    current_episode_text: str,
    entities_json: str,
    context_block: str = "",
) -> str:
    """
    关系抽取 prompt（仅抽关系，不抽实体属性；关系必须引用已知实体）。
    """
    return (
        "你是一个信息抽取助手。请从给定文本中抽取\"关系/事实边\"。\n\n"
        "要求：\n"
        "1) 只输出 JSON，不要输出任何额外文本。\n"
        "2) 只抽关系，不要新增实体；source/target 必须来自给定实体列表，且名称要完全一致。\n"
        "3) name 必须为 UPPER_SNAKE_CASE（如 WORKS_AT, OWNS, DEPENDS_ON）。\n"
        "4) fact 必须是可读、可验证的事实句子。\n"
        "5) valid_at/invalid_at 尽量给出；不确定则为 null。\n"
        "6) 顶层字段必须是 edges（不要输出 relationships/relations）；无关系也要输出 {\"edges\": []}。\n\n"
        f"当前时间：{current_episode_time}\n\n"
        f"上下文：\n{context_block}\n\n"
        f"已知实体（JSON）：\n{entities_json}\n\n"
        f"文本：\n{current_episode_text}\n"
    )


def build_relation_attributes_prompt(
    current_episode_time: str,
    current_episode_text: str,
    edges_json: str,
) -> str:
    """
    关系属性抽取 prompt（为已抽取的关系补充 qualifiers/attributes 等）。
    """
    return (
        "你是一个信息抽取助手。请基于给定文本，为\"已知关系列表\"补充关系属性（qualifiers/attributes）。\n\n"
        "要求：\n"
        "1) 只输出 JSON，不要输出任何额外文本。\n"
        "2) 不要新增关系，只能按 index 对已有关系补充字段。\n"
        "3) qualifiers/attributes 必须是对象；缺失则输出空对象 {}。\n"
        "4) confidence 可选，范围 0~1；polarity 可选：1 表示肯定，-1 表示否定/撤销。\n"
        "5) 顶层字段必须是 edges；无关系也要输出 {\"edges\": []}。\n\n"
        f"当前时间：{current_episode_time}\n\n"
        f"已知关系（JSON，含 index）：\n{edges_json}\n\n"
        f"文本：\n{current_episode_text}\n"
    )


def build_reflect_entities_prompt(
    current_episode_time: str,
    current_episode_text: str,
    existing_entities_json: str,
) -> str:
    """
    反思补全实体 prompt：只输出缺失的新增实体。
    """
    return (
        "你是一个信息抽取助手。现在请做反思：检查给定文本中是否还有\"缺失实体\"。\n\n"
        "要求：\n"
        "1) 只输出 JSON，不要输出任何额外文本。\n"
        "2) 只输出新增实体（不在 existing_entities 里的），否则不要重复。\n"
        "3) 同名合并、去代词、去噪。\n"
        "4) 顶层字段必须是 entities；无新增则输出 {\"entities\": []}。\n\n"
        f"当前时间：{current_episode_time}\n\n"
        f"已有实体（JSON）：\n{existing_entities_json}\n\n"
        f"文本：\n{current_episode_text}\n"
    )


def build_reflect_relations_prompt(
    current_episode_time: str,
    current_episode_text: str,
    entities_json: str,
    existing_edges_json: str,
) -> str:
    """
    反思补全关系 prompt：只输出缺失的新增关系，且必须引用已知实体。
    """
    return (
        "你是一个信息抽取助手。现在请做反思：检查给定文本中是否还有\"缺失关系/事实边\"。\n\n"
        "要求：\n"
        "1) 只输出 JSON，不要输出任何额外文本。\n"
        "2) 只输出新增关系（不在 existing_edges 里的），否则不要重复。\n"
        "3) source/target 必须来自给定实体列表，且名称要完全一致。\n"
        "4) name 必须为 UPPER_SNAKE_CASE；fact 必须可读。\n"
        "5) 顶层字段必须是 edges；无新增则输出 {\"edges\": []}。\n\n"
        f"当前时间：{current_episode_time}\n\n"
        f"已知实体（JSON）：\n{entities_json}\n\n"
        f"已有关系（JSON）：\n{existing_edges_json}\n\n"
        f"文本：\n{current_episode_text}\n"
    )


# ============================================================================
# 辅助函数
# ============================================================================


def _canonical_fact_hash(fact: str) -> str:
    """计算事实的规范哈希"""
    return hashlib.sha256(fact.strip().lower().encode()).hexdigest()


def _normalize_entity_name(name: str) -> str:
    """规范化实体名"""
    return name.strip()


def _edge_key(rel: ExtractedRelation) -> str:
    """生成关系的唯一 key"""
    return f"{rel.source.lower()}::{rel.target.lower()}::{rel.name}::{_canonical_fact_hash(rel.fact)}"


_MULTI_RELATIONS = {
    "ALIAS_OF",
    "PRODUCES",
    "OPERATES_DATA_CENTER_IN",
    "COMPETES_WITH",
    "PART_OF",
    "RELATED_TO",
}

_ONE_RELATIONS = {"HEADQUARTERS_IN"}


def _parse_llm_json_response(response: str) -> Dict[str, Any]:
    """解析 LLM 返回的 JSON 响应"""
    import re

    # 尝试提取 JSON 对象
    json_str = re.search(r"\{.*\}", response, re.DOTALL)
    if json_str:
        try:
            return json.loads(json_str.group())
        except json.JSONDecodeError:
            pass

    # 尝试解析整个响应
    try:
        return json.loads(response)
    except json.JSONDecodeError:
        return {}


def _extract_entities_from_response(response: Dict[str, Any]) -> List[ExtractedEntity]:
    """从 LLM 响应中提取实体"""
    items: List[Any] = []
    if isinstance(response, dict) and isinstance(response.get("entities"), list):
        items = response.get("entities", [])
    elif isinstance(response, list):
        items = response

    entities: List[ExtractedEntity] = []
    seen: Dict[str, ExtractedEntity] = {}

    for item in items:
        if not isinstance(item, dict):
            continue
        nm = (item.get("name") or "").strip()
        if not nm:
            continue

        key = nm.lower()
        labels = item.get("labels") or ["Entity"]
        if isinstance(labels, str):
            labels = [labels]
        labels = [str(x) for x in labels if str(x).strip()]
        if not labels:
            labels = ["Entity"]

        ent = ExtractedEntity(
            name=nm,
            labels=labels,
            description=item.get("description"),
            attributes=item.get("attributes") or {},
        )

        if key in seen:
            # 合并描述与属性
            existing = seen[key]
            if not existing.description and ent.description:
                existing.description = ent.description
            existing.attributes.update(ent.attributes)
            # 合并标签
            labs = set(existing.labels)
            labs.update(ent.labels)
            existing.labels = sorted(labs)
        else:
            seen[key] = ent
            entities.append(ent)

    return entities


def _extract_relations_from_response(response: Dict[str, Any]) -> List[ExtractedRelation]:
    """从 LLM 响应中提取关系"""
    items: List[Any] = []
    if isinstance(response, dict):
        raw = response.get("edges") or response.get("relationships") or response.get("relations")
        if isinstance(raw, list):
            items = raw
    elif isinstance(response, list):
        items = response

    relations: List[ExtractedRelation] = []

    for item in items:
        if not isinstance(item, dict):
            continue

        src = (item.get("source") or item.get("source_name") or item.get("src") or "").strip()
        dst = (item.get("target") or item.get("target_name") or item.get("dst") or "").strip()
        if not src or not dst:
            continue

        rel_name = (item.get("name") or "RELATED_TO").strip().upper()
        fact = (item.get("fact") or "").strip()
        if not fact:
            continue

        qualifiers = item.get("qualifiers") or {}
        confidence = item.get("confidence")
        polarity = item.get("polarity")

        rel = ExtractedRelation(
            source=src,
            target=dst,
            name=rel_name,
            fact=fact,
            valid_at=item.get("valid_at"),
            invalid_at=item.get("invalid_at"),
            cardinality=item.get("cardinality"),
            qualifiers=qualifiers if isinstance(qualifiers, dict) else {},
            attributes=item.get("attributes") or {} if isinstance(item.get("attributes"), dict) else {},
            confidence=float(confidence) if confidence is not None else None,
            polarity=int(polarity) if polarity is not None else None,
        )

        relations.append(rel)

    return relations


def _apply_entity_attributes(entities: List[ExtractedEntity], response: Dict[str, Any]) -> None:
    """应用实体属性到已有实体"""
    if not entities:
        return

    allowed = {e.name.lower() for e in entities}
    attr_by_name: Dict[str, Dict[str, Any]] = {}

    if isinstance(response, dict):
        ent_items = response.get("entities")
        if isinstance(ent_items, list):
            for ent in ent_items:
                if not isinstance(ent, dict):
                    continue
                nm = (ent.get("name") or "").strip()
                if nm and (not allowed or nm.lower() in allowed):
                    attr_by_name[nm.lower()] = ent.get("attributes") or {}

    for e in entities:
        extra = attr_by_name.get(e.name.lower())
        if isinstance(extra, dict):
            e.attributes.update(extra)


def _apply_relation_attributes(relations: List[ExtractedRelation], response: Dict[str, Any]) -> None:
    """应用关系属性到已有关系"""
    if not relations:
        return

    raw_items: List[Any] = []
    if isinstance(response, dict):
        edges_items = response.get("edges")
        if isinstance(edges_items, list):
            raw_items = edges_items

    for item in raw_items:
        if not isinstance(item, dict):
            continue
        idx = item.get("index")
        if not isinstance(idx, int) or not (0 <= idx < len(relations)):
            continue

        rel = relations[idx]
        q = item.get("qualifiers")
        a = item.get("attributes")
        if isinstance(q, dict):
            rel.qualifiers.update(q)
        if isinstance(a, dict):
            rel.attributes.update(a)
        if item.get("confidence") is not None:
            rel.confidence = float(item.get("confidence"))
        if item.get("polarity") is not None:
            rel.polarity = int(item.get("polarity"))


def _postprocess_relations(relations: List[ExtractedRelation]) -> None:
    """后处理关系：处理置信度、极性、基数等"""
    for rel in relations:
        # 从 qualifiers 提取 confidence/polarity
        if rel.confidence is None and rel.qualifiers.get("confidence") is not None:
            rel.confidence = float(rel.qualifiers["confidence"])
        if rel.polarity is None and rel.qualifiers.get("polarity") is not None:
            rel.polarity = int(rel.qualifiers["polarity"])

    # 多值关系不强制为 "one"
    for rel in relations:
        if rel.name in _MULTI_RELATIONS:
            rel.cardinality = None

    # 负极性关系不覆盖正事实
    for rel in relations:
        if rel.polarity is not None and rel.polarity < 0:
            rel.cardinality = None

    # 同一 source+relation 有多目标时，自动放宽为 many
    targets_by_key: Dict[tuple, set] = {}
    for rel in relations:
        key = (rel.source, rel.name)
        targets_by_key.setdefault(key, set()).add(rel.target)

    for (src, rel_name), targets in targets_by_key.items():
        if len(targets) > 1 and rel_name not in _ONE_RELATIONS:
            for rel in relations:
                if rel.source == src and rel.name == rel_name:
                    rel.cardinality = None


# ============================================================================
# 多步抽取器
# ============================================================================


class MultiStepGraphExtractor:
    """
    多步知识图谱抽取器

    实现策略：
    1. 实体抽取 (CNER)
    2. 实体属性补全
    3. 关系抽取 (RE)
    4. 关系属性补全
    5. 反思迭代 (默认2轮)
    """

    def __init__(
        self,
        llm: Optional[Any] = None,
        reflection_iters: int = 2,
    ):
        self.llm = llm
        self.reflection_iters = max(0, min(5, reflection_iters))

    @classmethod
    def create_default(cls, reflection_iters: int = 2) -> "MultiStepGraphExtractor":
        """创建默认实例"""
        return cls(llm=None, reflection_iters=reflection_iters)

    async def _generate_json(self, prompt: str) -> Dict[str, Any]:
        """调用 LLM 生成 JSON"""
        if self.llm is None:
            # 延迟创建 LLM 实例
            from langchain_openai import ChatOpenAI

            self.llm = ChatOpenAI(
                model=settings.DEEPSEEK_MODEL,
                temperature=0,
                api_key=settings.DEEPSEEK_API_KEY if settings.DEEPSEEK_API_KEY else None,
                base_url=settings.DEEPSEEK_BASE_URL,
            )

        try:
            response = await self.llm.ainvoke(prompt)
            text = response.content if hasattr(response, "content") else str(response)
            return _parse_llm_json_response(text)
        except Exception as e:
            logger.warning(f"LLM generation failed: {e}")
            return {}

    async def extract(
        self,
        text: str,
        episode_time: Optional[str] = None,
        context_block: str = "",
        episode_ref: Optional[str] = None,
    ) -> ExtractionResult:
        """
        执行多步抽取

        Args:
            text: 待抽取文本
            episode_time: 当前时间 (ISO格式)
            context_block: 上下文信息
            episode_ref: 证据片段引用

        Returns:
            ExtractionResult: 抽取结果
        """
        import datetime
        now = datetime.datetime.now(datetime.timezone.utc)
        current_time = episode_time or now.isoformat()

        entities: List[ExtractedEntity] = []
        relations: List[ExtractedRelation] = []
        episodes: List[str] = [episode_ref] if episode_ref else []

        # -------- Step 1: 实体抽取 --------
        ent_prompt = build_entity_extraction_prompt(
            current_episode_time=current_time,
            current_episode_text=text,
            context_block=context_block,
        )
        ent_out = await self._generate_json(ent_prompt)
        entities = _extract_entities_from_response(ent_out)
        logger.info(f"[GraphExtract] Step 1 - Entities: {len(entities)}")

        if not entities:
            logger.info("[GraphExtract] No entities found, skipping relation extraction")
            return ExtractionResult(entities=entities, relations=[], episodes=episodes)

        # -------- Step 2: 实体属性补全 --------
        try:
            entities_json = json.dumps(
                [{"name": e.name, "labels": e.labels, "description": e.description} for e in entities],
                ensure_ascii=False,
            )
        except Exception:
            entities_json = "[]"

        ent_attr_prompt = build_entity_attributes_prompt(
            current_episode_time=current_time,
            current_episode_text=text,
            entities_json=entities_json,
        )
        ent_attr_out = await self._generate_json(ent_attr_prompt)
        _apply_entity_attributes(entities, ent_attr_out)
        logger.info(f"[GraphExtract] Step 2 - Entity attributes applied")

        # -------- Step 3: 关系抽取 --------
        entities_json = json.dumps([{"name": e.name} for e in entities], ensure_ascii=False)
        rel_prompt = build_relation_extraction_prompt(
            current_episode_time=current_time,
            current_episode_text=text,
            entities_json=entities_json,
            context_block=context_block,
        )
        rel_out = await self._generate_json(rel_prompt)
        relations = _extract_relations_from_response(rel_out)
        logger.info(f"[GraphExtract] Step 3 - Relations: {len(relations)}")

        if not relations:
            logger.info("[GraphExtract] No relations found, returning entities only")
            _postprocess_relations(relations)
            return ExtractionResult(entities=entities, relations=relations, episodes=episodes)

        # -------- Step 4: 关系属性补全 --------
        edges_for_prompt = [
            {
                "index": i,
                "source": r.source,
                "target": r.target,
                "name": r.name,
                "fact": r.fact,
            }
            for i, r in enumerate(relations)
        ]
        edges_json = json.dumps(edges_for_prompt, ensure_ascii=False)

        rel_attr_prompt = build_relation_attributes_prompt(
            current_episode_time=current_time,
            current_episode_text=text,
            edges_json=edges_json,
        )
        rel_attr_out = await self._generate_json(rel_attr_prompt)
        _apply_relation_attributes(relations, rel_attr_out)
        logger.info(f"[GraphExtract] Step 4 - Relation attributes applied")

        # -------- Step 5: 反思迭代 --------
        edge_seen: Set[str] = {_edge_key(r) for r in relations}

        for i in range(self.reflection_iters):
            changed = False

            # 5a: 反思新增实体
            existing_entities_json = json.dumps([{"name": e.name} for e in entities], ensure_ascii=False)
            reflect_ent_prompt = build_reflect_entities_prompt(
                current_episode_time=current_time,
                current_episode_text=text,
                existing_entities_json=existing_entities_json,
            )
            reflect_ent_out = await self._generate_json(reflect_ent_prompt)
            new_entities = _extract_entities_from_response(reflect_ent_out)

            # 只保留真正新增的
            existing_keys = {e.name.lower() for e in entities}
            new_entities = [e for e in new_entities if e.name.lower() not in existing_keys]

            if new_entities:
                changed = True
                # 为新增实体补属性
                new_entities_json = json.dumps(
                    [{"name": e.name, "labels": e.labels, "description": e.description} for e in new_entities],
                    ensure_ascii=False,
                )
                ent_attr_prompt2 = build_entity_attributes_prompt(
                    current_episode_time=current_time,
                    current_episode_text=text,
                    entities_json=new_entities_json,
                )
                ent_attr_out2 = await self._generate_json(ent_attr_prompt2)
                _apply_entity_attributes(new_entities, ent_attr_out2)

                # 合并新增实体（去重）
                seen_new = {e.name.lower() for e in new_entities}
                for ne in new_entities:
                    if ne.name.lower() not in existing_keys:
                        entities.append(ne)

                logger.info(f"[GraphExtract] Step 5.{i}a - New entities: {len(new_entities)}")

            # 5b: 反思新增关系
            entities_json = json.dumps([{"name": e.name} for e in entities], ensure_ascii=False)
            existing_edges_json = json.dumps(
                [{"source": r.source, "target": r.target, "name": r.name, "fact": r.fact} for r in relations],
                ensure_ascii=False,
            )
            reflect_rel_prompt = build_reflect_relations_prompt(
                current_episode_time=current_time,
                current_episode_text=text,
                entities_json=entities_json,
                existing_edges_json=existing_edges_json,
            )
            reflect_rel_out = await self._generate_json(reflect_rel_prompt)
            new_relations = _extract_relations_from_response(reflect_rel_out)

            # 只保留真正新增的
            truly_new = []
            for nr in new_relations:
                k = _edge_key(nr)
                if k not in edge_seen:
                    edge_seen.add(k)
                    truly_new.append(nr)

            if truly_new:
                changed = True
                # 为新增关系补属性
                edges_for_prompt2 = [
                    {"index": i, "source": r.source, "target": r.target, "name": r.name, "fact": r.fact}
                    for i, r in enumerate(truly_new)
                ]
                edges_json2 = json.dumps(edges_for_prompt2, ensure_ascii=False)

                rel_attr_prompt2 = build_relation_attributes_prompt(
                    current_episode_time=current_time,
                    current_episode_text=text,
                    edges_json=edges_json2,
                )
                rel_attr_out2 = await self._generate_json(rel_attr_prompt2)
                _apply_relation_attributes(truly_new, rel_attr_out2)

                relations.extend(truly_new)
                logger.info(f"[GraphExtract] Step 5.{i}b - New relations: {len(truly_new)}")

            if not changed:
                logger.info(f"[GraphExtract] Step 5 - Early stop at iteration {i + 1}")
                break

        # -------- 后处理 --------
        _postprocess_relations(relations)

        return ExtractionResult(entities=entities, relations=relations, episodes=episodes)


# ============================================================================
# 便捷函数
# ============================================================================


async def extract_graph_from_text(
    text: str,
    episode_time: Optional[str] = None,
    context_block: str = "",
    episode_ref: Optional[str] = None,
    reflection_iters: int = 2,
) -> ExtractionResult:
    """
    从文本中抽取知识图谱

    Args:
        text: 待抽取文本
        episode_time: 当前时间 (ISO格式)
        context_block: 上下文信息
        episode_ref: 证据片段引用
        reflection_iters: 反思迭代轮数

    Returns:
        ExtractionResult: 抽取结果
    """
    extractor = MultiStepGraphExtractor.create_default(reflection_iters=reflection_iters)
    return await extractor.extract(
        text=text,
        episode_time=episode_time,
        context_block=context_block,
        episode_ref=episode_ref,
    )
