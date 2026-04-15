"""
AssetOrganizeAgent - LangGraph-based asset organization agent with graph clustering.
"""
from __future__ import annotations

import logging
from typing import Any

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda
from langgraph.graph import END, StateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.core import AssetOrganizeState
from app.core.config import settings
from app.db.models import Users
from app.services.asset_service import AssetService
from app.services.base import get_llm_client

logger = logging.getLogger(__name__)


class AssetOrganizeAgent:
    """Agent for organizing assets using graph-based clustering."""

    def __init__(self, db: AsyncSession):
        """
        Initialize AssetOrganizeAgent.

        Args:
            db: AsyncSession for database operations
        """
        self.db = db
        self.asset_service = AssetService(db)
        self.graph = self._build_graph()

    def _build_graph(self) -> StateGraph:
        """Build the LangGraph StateGraph for asset organization."""
        builder = StateGraph(AssetOrganizeState)

        builder.add_node("load_assets", RunnableLambda(self._load_assets_node))
        builder.add_node("extract_features", RunnableLambda(self._extract_features_node))
        builder.add_node("graph_clustering", RunnableLambda(self._graph_clustering_node))
        builder.add_node("generate_summary", RunnableLambda(self._generate_summary_node))
        builder.add_node("update_graph", RunnableLambda(self._update_graph_node))
        builder.add_node("prepare_publication", RunnableLambda(self._prepare_publication_node))

        builder.add_edge("load_assets", "extract_features")
        builder.add_edge("extract_features", "graph_clustering")
        builder.add_edge("graph_clustering", "generate_summary")
        builder.add_edge("generate_summary", "update_graph")
        builder.add_edge("update_graph", "prepare_publication")
        builder.add_edge("prepare_publication", END)

        builder.set_entry_point("load_assets")
        return builder.compile()

    async def _load_assets_node(self, state: AssetOrganizeState) -> AssetOrganizeState:
        """Load assets to be organized."""
        asset_ids = state.get("asset_ids", [])
        space_id = state.get("space_id", "")

        if not asset_ids:
            state["asset_ids"] = []
            state["clustering_result"] = {"error": "No assets provided"}
            return state

        try:
            assets = []
            user = state.get("user")
            for aid in asset_ids:
                try:
                    asset = await self.asset_service.get_asset(space_id, aid, user)
                    assets.append({
                        "asset_id": aid,
                        "name": asset.get("title", f"Asset {aid}"),
                        "content": asset.get("content_markdown", ""),
                        "category": asset.get("asset_type", "knowledge_report"),
                    })
                except Exception:
                    pass

            state["asset_ids"] = [a["asset_id"] for a in assets]
            state["clustering_result"] = {"assets_loaded": len(assets), "assets": assets}

        except Exception as e:
            logger.error(f"Failed to load assets: {e}")
            state["clustering_result"] = {"error": f"Failed to load assets: {str(e)}"}

        return state

    async def _extract_features_node(self, state: AssetOrganizeState) -> AssetOrganizeState:
        """Extract features from assets for clustering."""
        clustering_result = state.get("clustering_result", {})
        assets = clustering_result.get("assets", [])

        if not assets:
            return state

        try:
            llm = get_llm_client(temperature=0.3)

            # Use LLM to extract features from each asset
            feature_prompt = ChatPromptTemplate.from_messages([
                ("system", """你是一个资产分析助手。从给定资产中提取关键特征用于聚类分析。

分析维度：
1. category: 资产类别（技术文档、市场报告、知识库等）
2. topic: 主要主题
3. entities: 提到的关键实体
4. tags: 相关标签（从已有标签和内容推断）

输出JSON格式：
{
    "category": "类别",
    "topic": "主要主题",
    "entities": ["实体1", "实体2"],
    "inferred_tags": ["标签1", "标签2"]
}

只返回JSON。"""),
                ("human", "Asset name: {name}\nContent: {content[:500]}")
            ])

            chain = feature_prompt | llm | StrOutputParser()

            for asset in assets:
                try:
                    result = await chain.ainvoke({
                        "name": asset.get("name", ""),
                        "content": asset.get("content", "")[:2000]
                    })

                    import re
                    json_match = re.search(r'\{[^}]+\}', result, re.DOTALL)
                    if json_match:
                        import json
                        features = json.loads(json_match.group())
                        asset["extracted_features"] = features
                        asset["category"] = features.get("category", asset.get("category"))
                        asset["inferred_tags"] = features.get("inferred_tags", [])
                        asset["entities"] = features.get("entities", [])
                    else:
                        asset["extracted_features"] = {}

                except Exception as e:
                    logger.warning(f"Feature extraction failed for {asset.get('asset_id')}: {e}")
                    asset["extracted_features"] = {}

            state["clustering_result"] = clustering_result

        except Exception as e:
            logger.error(f"Feature extraction failed: {e}")

        return state

    async def _graph_clustering_node(self, state: AssetOrganizeState) -> AssetOrganizeState:
        """Perform graph-based clustering of assets."""
        clustering_result = state.get("clustering_result", {})
        assets = clustering_result.get("assets", [])

        if not assets:
            return state

        try:
            # Build similarity graph based on extracted features
            clusters = []
            assigned = set()

            # Group by category first (primary clustering dimension)
            category_groups: dict[str, list] = {}
            for asset in assets:
                cat = asset.get("category", "uncategorized") or "uncategorized"
                if cat not in category_groups:
                    category_groups[cat] = []
                category_groups[cat].append(asset)

            # Create clusters from category groups
            cluster_id = 0
            for category, group in category_groups.items():
                if len(group) >= 1:  # Each category becomes a cluster
                    # Further split large clusters by topic similarity
                    if len(group) > 10:
                        # Use entity overlap for sub-clustering
                        entity_groups = self._group_by_entity_overlap(group)
                        for sub_group in entity_groups:
                            cluster = {
                                "cluster_id": f"cluster_{cluster_id}",
                                "category": category,
                                "asset_ids": [a["asset_id"] for a in sub_group],
                                "size": len(sub_group),
                                "method": "entity_overlap"
                            }
                            clusters.append(cluster)
                            cluster_id += 1
                    else:
                        cluster = {
                            "cluster_id": f"cluster_{cluster_id}",
                            "category": category,
                            "asset_ids": [a["asset_id"] for a in group],
                            "size": len(group),
                            "method": "category"
                        }
                        clusters.append(cluster)
                        cluster_id += 1

            clustering_result["clusters"] = clusters
            clustering_result["num_clusters"] = len(clusters)
            state["clustering_result"] = clustering_result

        except Exception as e:
            logger.error(f"Graph clustering failed: {e}")
            clustering_result["clustering_error"] = str(e)
            state["clustering_result"] = clustering_result

        return state

    def _group_by_entity_overlap(self, assets: list) -> list[list]:
        """Group assets by entity overlap using simple community detection."""
        if not assets:
            return []

        # Build adjacency based on entity overlap
        n = len(assets)
        adjacency: dict[int, set[int]] = {i: set() for i in range(n)}

        for i in range(n):
            entities_i = set(assets[i].get("entities", []))
            for j in range(i + 1, n):
                entities_j = set(assets[j].get("entities", []))
                overlap = len(entities_i & entities_j)
                if overlap > 0:
                    # Edge weight based on overlap
                    adjacency[i].add(j)
                    adjacency[j].add(i)

        # Label propagation for community detection
        labels = list(range(n))  # Each node starts with own label

        def propagate():
            changed = False
            for i in range(n):
                neighbor_labels = [labels[j] for j in adjacency[i]]
                if neighbor_labels:
                    most_common = max(set(neighbor_labels), key=neighbor_labels.count)
                    if most_common != labels[i]:
                        labels[i] = most_common
                        changed = True
            return changed

        # Run label propagation
        for _ in range(10):  # Max iterations
            if not propagate():
                break

        # Group by label
        groups: dict[int, list] = {}
        for i, label in enumerate(labels):
            if label not in groups:
                groups[label] = []
            groups[label].append(assets[i])

        return list(groups.values())

    async def _generate_summary_node(self, state: AssetOrganizeState) -> AssetOrganizeState:
        """Generate summary report for the clustering."""
        clustering_result = state.get("clustering_result", {})
        clusters = clustering_result.get("clusters", [])

        if not clusters:
            state["summary_report"] = "No clusters generated"
            return state

        try:
            llm = get_llm_client(temperature=0.3)

            # Build cluster descriptions
            cluster_descriptions = []
            for cluster in clusters:
                assets_in_cluster = [
                    a for a in clustering_result.get("assets", [])
                    if a["asset_id"] in cluster["asset_ids"]
                ]
                names = [a.get("name", "") for a in assets_in_cluster[:5]]
                category = cluster.get("category", "Unknown")

                desc = f"Cluster {cluster['cluster_id']} ({category}): {', '.join(names)}"
                if cluster["size"] > 5:
                    desc += f" and {cluster['size'] - 5} more"
                cluster_descriptions.append(desc)

            prompt = ChatPromptTemplate.from_messages([
                ("system", "你是一个资产整理助手。根据聚类结果生成整理报告。"),
                ("human", "聚类结果:\n{clusters}\n\n请生成一份简洁的资产整理报告，包括：\n1. 整体聚类概况\n2. 各聚类的简要描述\n3. 整理建议")
            ])

            chain = prompt | llm | StrOutputParser()
            result = await chain.ainvoke({"clusters": "\n".join(cluster_descriptions)})

            state["summary_report"] = result

        except Exception as e:
            logger.error(f"Summary generation failed: {e}")
            state["summary_report"] = f"Failed to generate summary: {str(e)}"

        return state

    async def _update_graph_node(self, state: AssetOrganizeState) -> AssetOrganizeState:
        """Update Neo4j graph with cluster markers."""
        clustering_result = state.get("clustering_result", {})
        clusters = clustering_result.get("clusters", [])

        if not clusters:
            state["graph_updates"] = []
            return state

        neo4j_uri = (settings.NEO4J_URI or "").strip()
        if not neo4j_uri:
            logger.warning("Neo4j not configured, skipping graph update")
            state["graph_updates"] = [{"status": "skipped", "reason": "Neo4j not configured"}]
            return state

        try:
            from neo4j import GraphDatabase

            driver = GraphDatabase.driver(
                neo4j_uri, auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)
            )

            updates = []

            with driver.session(database=settings.NEO4J_DATABASE) as session:
                for cluster in clusters:
                    cluster_id = cluster.get("cluster_id")
                    category = cluster.get("category")
                    asset_ids = cluster.get("asset_ids", [])

                    for asset_id in asset_ids:
                        try:
                            session.run(
                                """
                                MATCH (a:Asset {asset_id: $asset_id})
                                SET a.cluster_id = $cluster_id,
                                    a.cluster_category = $category
                                """,
                                asset_id=asset_id,
                                cluster_id=cluster_id,
                                category=category
                            )
                            updates.append({
                                "asset_id": asset_id,
                                "cluster_id": cluster_id,
                                "status": "updated"
                            })
                        except Exception as e:
                            logger.warning(f"Failed to update asset {asset_id}: {e}")
                            updates.append({
                                "asset_id": asset_id,
                                "cluster_id": cluster_id,
                                "status": "failed",
                                "error": str(e)
                            })

            driver.close()

            state["graph_updates"] = updates

        except Exception as e:
            logger.error(f"Graph update failed: {e}")
            state["graph_updates"] = [{"status": "error", "error": str(e)}]

        return state

    async def _prepare_publication_node(self, state: AssetOrganizeState) -> AssetOrganizeState:
        """Prepare assets for publication with cluster metadata."""
        clustering_result = state.get("clustering_result", {})
        clusters = clustering_result.get("clusters", [])

        publication_ready = True
        if not clusters:
            publication_ready = False

        state["publication_ready"] = publication_ready
        return state

    async def run(
        self,
        asset_ids: list[str],
        space_id: str,
        user: Users,
    ) -> dict[str, Any]:
        """
        Run the asset organization pipeline.

        Args:
            asset_ids: List of asset IDs to organize
            space_id: Space public ID
            user: Current user

        Returns:
            Dict containing organization results
        """
        initial_state: AssetOrganizeState = {
            "asset_ids": asset_ids,
            "space_id": space_id,
            "user": user,
            "clustering_result": {},
            "graph_updates": [],
            "summary_report": None,
            "publication_ready": False
        }

        try:
            result = await self.graph.ainvoke(initial_state)
            return {
                "success": True,
                "asset_ids": result.get("asset_ids", []),
                "clusters": result.get("clustering_result", {}).get("clusters", []),
                "num_clusters": result.get("clustering_result", {}).get("num_clusters", 0),
                "summary_report": result.get("summary_report"),
                "graph_updates": result.get("graph_updates", []),
                "publication_ready": result.get("publication_ready", False)
            }
        except Exception as e:
            logger.exception(f"AssetOrganizeAgent error: {e}")
            return {
                "success": False,
                "error": str(e)
            }
