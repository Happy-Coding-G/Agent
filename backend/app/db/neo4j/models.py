"""
Neo4j Graph Data Models (Simplified)

Simplified model based on Episode + Entity + Community:

1. Episode - 证据单元 (evidence unit, typically a chunk)
   - Source for entities
   - Target for community clustering

2. Entity - 从证据中抽取出的结构化知识
   - Extracted from episodes
   - Linked by MENTIONS edge

3. Community - Episode聚类结果
   - Groups related episodes
   - Represents a personal asset unit
   - Links to relevant Agents for processing

Edge Types:
- MENTIONS: Episode -> Entity (evidence mentions entity)
- IN_COMMUNITY: Episode -> Community (episode belongs to community)
- RELATED: Episode -> Episode (semantic relationship for clustering)
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid


# ============================================================================
# Node Models
# ============================================================================

@dataclass
class GraphEpisode:
    """
    Graph Episode Node - Evidence unit.

    Typically corresponds to a document chunk.
    Primary key: episode_ref + user_id

    This is the primary node for community clustering.

    Labels: ["GraphEpisode"]
    """
    episode_ref: str  # Stable reference (usually chunk_id)
    user_id: str
    content: str  # Evidence text (the chunk content)
    community_id: Optional[str] = None  # Community this episode belongs to
    source: Optional[str] = None  # Source type: "file", "web", "text"
    name: Optional[str] = None  # Episode name
    valid_at_ms: Optional[int] = None
    valid_at: Optional[str] = None
    chunk_index: Optional[int] = None  # Chunk sequence number
    media_id: Optional[str] = None  # Source media identifier
    tags: List[str] = field(default_factory=list)  # Tags for clustering
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    @classmethod
    def new(cls, episode_ref: str, user_id: str, content: str, **kwargs) -> "GraphEpisode":
        """Factory method."""
        return cls(episode_ref=episode_ref, user_id=user_id, content=content, **kwargs)

    def to_cypher_params(self) -> Dict[str, Any]:
        """Convert to Cypher parameter dict."""
        return {
            "episode_ref": self.episode_ref,
            "user_id": self.user_id,
            "community_id": self.community_id,
            "source": self.source,
            "name": self.name,
            "content": self.content,
            "valid_at_ms": self.valid_at_ms,
            "valid_at": self.valid_at,
            "chunk_index": self.chunk_index,
            "media_id": self.media_id,
            "tags": self.tags,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass
class GraphEntity:
    """
    Graph Entity Node - Extracted knowledge from episodes.

    Represents persons, organizations, locations, projects, concepts, etc.
    Primary key: uuid (MERGE by uuid)

    Labels: ["GraphEntity"] + custom labels
    """
    uuid: str  # Stable primary key
    name: str
    user_id: str  # User scope
    community_id: Optional[str] = None  # Community this entity belongs to
    labels: List[str] = field(default_factory=list)  # e.g., ["Person", "Organization", "Concept"]
    description: Optional[str] = None
    summary: Optional[str] = None
    attributes_json: Optional[Dict[str, Any]] = None  # Extended attributes
    media_id: Optional[str] = None
    episode_ref: Optional[str] = None  # Source episode
    valid_at_ms: Optional[int] = None
    valid_at: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    @classmethod
    def new(cls, name: str, user_id: str, **kwargs) -> "GraphEntity":
        """Factory method with auto uuid generation."""
        return cls(
            uuid=str(uuid.uuid4()),
            name=name,
            user_id=user_id,
            **kwargs
        )

    def to_cypher_params(self) -> Dict[str, Any]:
        """Convert to Cypher parameter dict."""
        return {
            "uuid": self.uuid,
            "name": self.name,
            "user_id": self.user_id,
            "community_id": self.community_id,
            "labels": self.labels,
            "description": self.description,
            "summary": self.summary,
            "attributes_json": self.attributes_json,
            "media_id": self.media_id,
            "episode_ref": self.episode_ref,
            "valid_at_ms": self.valid_at_ms,
            "valid_at": self.valid_at,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass
class GraphCommunity:
    """
    Graph Community Node - Episode clustering result.

    Groups related episodes into a personal asset unit.
    Primary key: uuid

    A community represents:
    - A thematic cluster of related episodes
    - A personal digital asset that can be processed by agents
    - The unit for organization and management

    Labels: ["GraphCommunity"]
    """
    uuid: str
    name: str
    user_id: str
    description: Optional[str] = None
    summary: Optional[str] = None  # AI-generated summary of the community
    episode_count: int = 0  # Number of episodes in this community
    agent_type: Optional[str] = None  # Suggested agent for processing: "qa", "review", "trade"
    tags: List[str] = field(default_factory=list)  # Topic tags
    metadata_json: Optional[Dict[str, Any]] = None  # Extended metadata
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    @classmethod
    def new(cls, name: str, user_id: str, **kwargs) -> "GraphCommunity":
        """Factory method with auto uuid generation."""
        return cls(
            uuid=str(uuid.uuid4()),
            name=name,
            user_id=user_id,
            **kwargs
        )

    def to_cypher_params(self) -> Dict[str, Any]:
        """Convert to Cypher parameter dict."""
        return {
            "uuid": self.uuid,
            "name": self.name,
            "user_id": self.user_id,
            "description": self.description,
            "summary": self.summary,
            "episode_count": self.episode_count,
            "agent_type": self.agent_type,
            "tags": self.tags,
            "metadata_json": self.metadata_json,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


# ============================================================================
# Edge (Relationship) Models
# ============================================================================

@dataclass
class GraphMentions:
    """
    Graph Mentions Edge - Episode mentions Entity.

    Episode -> Entity relationship showing which entities are mentioned
    in a piece of evidence (episode/chunk).

    Relationship type: "MENTIONS"
    """
    uuid: str = field(default_factory=lambda: str(uuid.uuid4()))
    fact: Optional[str] = None  # The mention context
    fact_hash: Optional[str] = None  # For deduplication
    confidence: Optional[float] = None  # Extraction confidence
    user_id: Optional[str] = None
    community_id: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)

    def to_cypher_params(self) -> Dict[str, Any]:
        """Convert to Cypher parameter dict."""
        return {
            "uuid": self.uuid,
            "fact": self.fact,
            "fact_hash": self.fact_hash,
            "confidence": self.confidence,
            "user_id": self.user_id,
            "community_id": self.community_id,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class GraphInCommunity:
    """
    Graph In Community Edge - Episode belongs to Community.

    Episode -> Community membership relationship.

    Relationship type: "IN_COMMUNITY"
    """
    role: Optional[str] = None  # "core", "peripheral", "outlier"
    score: Optional[float] = None  # Membership score
    created_at: datetime = field(default_factory=datetime.utcnow)

    def to_cypher_params(self) -> Dict[str, Any]:
        """Convert to Cypher parameter dict."""
        return {
            "role": self.role,
            "score": self.score,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class GraphRelated:
    """
    Graph Related Edge - Episode relates to Episode.

    Semantic relationship between episodes (for clustering).

    Relationship type: "RELATED"
    """
    reason: Optional[str] = None  # Relationship reason: "topic", "entity", "temporal"
    score: Optional[float] = None  # Similarity score
    user_id: Optional[str] = None
    community_id: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)

    def to_cypher_params(self) -> Dict[str, Any]:
        """Convert to Cypher parameter dict."""
        return {
            "reason": self.reason,
            "score": self.score,
            "user_id": self.user_id,
            "community_id": self.community_id,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class GraphLinkedTo:
    """
    Graph Linked To Edge - Entity relates to Entity.

    Structural relationship between entities extracted from episodes.

    Relationship type: "LINKED_TO"
    """
    uuid: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = "LINKED_TO"  # Relationship name
    fact: Optional[str] = None  # Relationship description
    fact_hash: Optional[str] = None  # For deduplication
    user_id: Optional[str] = None
    community_id: Optional[str] = None
    episode_ref: Optional[str] = None  # Source episode
    created_at: datetime = field(default_factory=datetime.utcnow)

    def to_cypher_params(self) -> Dict[str, Any]:
        """Convert to Cypher parameter dict."""
        return {
            "uuid": self.uuid,
            "name": self.name,
            "fact": self.fact,
            "fact_hash": self.fact_hash,
            "user_id": self.user_id,
            "community_id": self.community_id,
            "episode_ref": self.episode_ref,
            "created_at": self.created_at.isoformat(),
        }
