"""
Neo4j Graph Database Models and Utilities (Simplified)

Simplified model focusing on Episode + Entity + Community:

Node Types:
- GraphEpisode: Evidence unit node (typically a document chunk)
- GraphEntity: Extracted knowledge node (persons, organizations, concepts)
- GraphCommunity: Episode clustering result (personal asset unit)

Edge Types:
- MENTIONS: Episode -> Entity (evidence mentions entity)
- IN_COMMUNITY: Episode -> Community (episode belongs to community)
- RELATED: Episode -> Episode (semantic relationship for clustering)
- LINKED_TO: Entity -> Entity (structural relationship)

Scope Fields:
- user_id: Primary isolation field
- community_id: Post-writeback clustering label
- media_id: Source media identifier
"""
from app.db.neo4j.models import (
    GraphEpisode,
    GraphEntity,
    GraphCommunity,
    GraphMentions,
    GraphInCommunity,
    GraphRelated,
    GraphLinkedTo,
)
from app.db.neo4j.driver import Neo4jDriver, get_neo4j_driver
from app.db.neo4j.crud import (
    merge_episode,
    merge_entity,
    merge_community,
    merge_mentions,
    merge_in_community,
    merge_related,
    merge_linked_to,
    query_episodes_by_community,
    query_entities_by_community,
    query_communities_by_user,
    query_mentions_by_episode,
    query_related_episodes,
    search_entities,
    get_entity_facts,
    get_community_stats,
    delete_episode,
    delete_community,
    update_episode_community,
    update_community_episode_count,
)

__all__ = [
    # Node Models
    "GraphEpisode",
    "GraphEntity",
    "GraphCommunity",
    # Edge Models
    "GraphMentions",
    "GraphInCommunity",
    "GraphRelated",
    "GraphLinkedTo",
    # Driver
    "Neo4jDriver",
    "get_neo4j_driver",
    # Node CRUD
    "merge_episode",
    "merge_entity",
    "merge_community",
    # Edge CRUD
    "merge_mentions",
    "merge_in_community",
    "merge_related",
    "merge_linked_to",
    # Query Operations
    "query_episodes_by_community",
    "query_entities_by_community",
    "query_communities_by_user",
    "query_mentions_by_episode",
    "query_related_episodes",
    "search_entities",
    "get_entity_facts",
    "get_community_stats",
    # Update/Delete Operations
    "delete_episode",
    "delete_community",
    "update_episode_community",
    "update_community_episode_count",
]
