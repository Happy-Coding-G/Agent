"""
Neo4j CRUD Operations (Simplified)

Provides database operations for the simplified graph models:
- Episode: Primary evidence unit, target for community clustering
- Entity: Extracted knowledge from episodes
- Community: Episode clustering result (personal asset unit)

Edge Types:
- MENTIONS: Episode -> Entity
- IN_COMMUNITY: Episode -> Community
- RELATED: Episode -> Episode
- LINKED_TO: Entity -> Entity
"""
import hashlib
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.db.neo4j.driver import get_neo4j_driver, Neo4jDriver
from app.db.neo4j.models import (
    GraphEntity,
    GraphEpisode,
    GraphCommunity,
    GraphMentions,
    GraphInCommunity,
    GraphRelated,
    GraphLinkedTo,
)

logger = logging.getLogger(__name__)

DATABASE = settings.NEO4J_DATABASE or "neo4j"


def _hash_fact(fact: str) -> str:
    """Compute canonical fact hash for deduplication."""
    s = (fact or "").strip().lower()
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


# ============================================================================
# Node Operations
# ============================================================================

def merge_episode(episode: GraphEpisode) -> Dict[str, Any]:
    """
    Merge an episode node into the graph.

    MERGE by episode_ref + user_id.
    """
    driver = get_neo4j_driver()
    params = episode.to_cypher_params()

    query = """
    MERGE (ep:GraphEpisode {episode_ref: $episode_ref, user_id: $user_id})
    SET ep.community_id = $community_id,
        ep.source = $source,
        ep.name = $name,
        ep.content = $content,
        ep.valid_at_ms = $valid_at_ms,
        ep.valid_at = $valid_at,
        ep.chunk_index = $chunk_index,
        ep.media_id = $media_id,
        ep.tags = $tags,
        ep.created_at = coalesce(ep.created_at, $created_at),
        ep.updated_at = $updated_at
    RETURN ep
    """

    with driver.session(database=DATABASE) as session:
        result = session.run(query, params)
        record = result.single()
        return dict(record["ep"]) if record else None


def merge_entity(entity: GraphEntity) -> Dict[str, Any]:
    """
    Merge an entity node into the graph.

    MERGE by uuid for stable identity.
    """
    driver = get_neo4j_driver()
    params = entity.to_cypher_params()

    merge_query = """
    MERGE (e:GraphEntity {uuid: $uuid})
    SET e.name = $name,
        e.user_id = $user_id,
        e.community_id = $community_id,
        e.description = $description,
        e.summary = $summary,
        e.attributes_json = $attributes_json,
        e.media_id = $media_id,
        e.episode_ref = $episode_ref,
        e.valid_at_ms = $valid_at_ms,
        e.valid_at = $valid_at,
        e.created_at = coalesce(e.created_at, $created_at),
        e.updated_at = $updated_at
    WITH e
    UNWIND $labels AS label
    CALL apoc.create.addLabels(e, [label]) YIELD node
    RETURN e
    """

    # Try with APOC first, fall back to simple MERGE
    try:
        with driver.session(database=DATABASE) as session:
            result = session.run(merge_query, params)
            record = result.single()
            return dict(record["e"]) if record else None
    except Exception as e:
        if "apoc" in str(e).lower():
            # Fall back to simple MERGE without label adding
            simple_query = """
            MERGE (e:GraphEntity {uuid: $uuid})
            SET e.name = $name,
                e.user_id = $user_id,
                e.community_id = $community_id,
                e.description = $description,
                e.summary = $summary,
                e.attributes_json = $attributes_json,
                e.media_id = $media_id,
                e.episode_ref = $episode_ref,
                e.valid_at_ms = $valid_at_ms,
                e.valid_at = $valid_at,
                e.created_at = coalesce(e.created_at, $created_at),
                e.updated_at = $updated_at
            RETURN e
            """
            with driver.session(database=DATABASE) as session:
                result = session.run(simple_query, params)
                record = result.single()
                return dict(record["e"]) if record else None
        raise


def merge_community(community: GraphCommunity) -> Dict[str, Any]:
    """
    Merge a community node into the graph.

    MERGE by uuid.
    """
    driver = get_neo4j_driver()
    params = community.to_cypher_params()

    query = """
    MERGE (c:GraphCommunity {uuid: $uuid})
    SET c.name = $name,
        c.user_id = $user_id,
        c.description = $description,
        c.summary = $summary,
        c.episode_count = $episode_count,
        c.agent_type = $agent_type,
        c.tags = $tags,
        c.metadata_json = $metadata_json,
        c.created_at = coalesce(c.created_at, $created_at),
        c.updated_at = $updated_at
    RETURN c
    """

    with driver.session(database=DATABASE) as session:
        result = session.run(query, params)
        record = result.single()
        return dict(record["c"]) if record else None


# ============================================================================
# Edge Operations
# ============================================================================

def merge_mentions(
    from_episode_ref: str,
    from_user_id: str,
    to_entity_uuid: str,
    mentions: Optional[GraphMentions] = None
) -> Optional[Dict[str, Any]]:
    """
    Create a MENTIONS edge from Episode to Entity.

    Episode mentions an entity in its content.
    """
    driver = get_neo4j_driver()
    mentions = mentions or GraphMentions()
    params = {
        **mentions.to_cypher_params(),
        "from_episode_ref": from_episode_ref,
        "from_user_id": from_user_id,
        "to_entity_uuid": to_entity_uuid,
    }

    query = """
    MATCH (ep:GraphEpisode {episode_ref: $from_episode_ref, user_id: $from_user_id})
    MATCH (e:GraphEntity {uuid: $to_entity_uuid})
    MERGE (ep)-[r:MENTIONS {uuid: $uuid}]->(e)
    SET r.fact = $fact,
        r.fact_hash = $fact_hash,
        r.confidence = $confidence,
        r.user_id = $user_id,
        r.community_id = $community_id,
        r.created_at = coalesce(r.created_at, $created_at)
    RETURN r
    """

    with driver.session(database=DATABASE) as session:
        result = session.run(query, params)
        record = result.single()
        return dict(record["r"]) if record else None


def merge_in_community(
    episode_ref: str,
    episode_user_id: str,
    community_uuid: str,
    in_community: Optional[GraphInCommunity] = None
) -> bool:
    """
    Create an IN_COMMUNITY edge from Episode to Community.

    Episode belongs to a community (cluster).
    """
    driver = get_neo4j_driver()
    in_community = in_community or GraphInCommunity()
    params = {
        **in_community.to_cypher_params(),
        "episode_ref": episode_ref,
        "episode_user_id": episode_user_id,
        "community_uuid": community_uuid,
    }

    query = """
    MATCH (ep:GraphEpisode {episode_ref: $episode_ref, user_id: $episode_user_id})
    MATCH (c:GraphCommunity {uuid: $community_uuid})
    MERGE (ep)-[r:IN_COMMUNITY]->(c)
    SET r.role = $role,
        r.score = $score,
        r.created_at = coalesce(r.created_at, $created_at)
    RETURN r
    """

    with driver.session(database=DATABASE) as session:
        result = session.run(query, params)
        return result.single() is not None


def merge_related(
    from_episode_ref: str,
    from_user_id: str,
    to_episode_ref: str,
    to_user_id: str,
    related: Optional[GraphRelated] = None
) -> bool:
    """
    Create a RELATED edge between two Episodes.

    Episodes have semantic relationships for clustering.
    """
    driver = get_neo4j_driver()
    related = related or GraphRelated()
    params = {
        **related.to_cypher_params(),
        "from_episode_ref": from_episode_ref,
        "from_user_id": from_user_id,
        "to_episode_ref": to_episode_ref,
        "to_user_id": to_user_id,
    }

    query = """
    MATCH (ep1:GraphEpisode {episode_ref: $from_episode_ref, user_id: $from_user_id})
    MATCH (ep2:GraphEpisode {episode_ref: $to_episode_ref, user_id: $to_user_id})
    MERGE (ep1)-[r:RELATED]->(ep2)
    SET r.reason = $reason,
        r.score = $score,
        r.user_id = $user_id,
        r.community_id = $community_id,
        r.created_at = coalesce(r.created_at, $created_at)
    RETURN r
    """

    with driver.session(database=DATABASE) as session:
        result = session.run(query, params)
        return result.single() is not None


def merge_linked_to(
    from_entity_uuid: str,
    to_entity_uuid: str,
    linked_to: Optional[GraphLinkedTo] = None
) -> Optional[Dict[str, Any]]:
    """
    Create a LINKED_TO edge between two Entities.

    Entities have structural relationships.
    """
    driver = get_neo4j_driver()
    linked_to = linked_to or GraphLinkedTo()
    params = {
        **linked_to.to_cypher_params(),
        "from_entity_uuid": from_entity_uuid,
        "to_entity_uuid": to_entity_uuid,
    }

    query = """
    MATCH (e1:GraphEntity {uuid: $from_entity_uuid})
    MATCH (e2:GraphEntity {uuid: $to_entity_uuid})
    MERGE (e1)-[r:LINKED_TO {uuid: $uuid}]->(e2)
    SET r.name = $name,
        r.fact = $fact,
        r.fact_hash = $fact_hash,
        r.user_id = $user_id,
        r.community_id = $community_id,
        r.episode_ref = $episode_ref,
        r.created_at = coalesce(r.created_at, $created_at)
    RETURN r
    """

    with driver.session(database=DATABASE) as session:
        result = session.run(query, params)
        record = result.single()
        return dict(record["r"]) if record else None


# ============================================================================
# Query Operations
# ============================================================================

def query_episodes_by_community(
    community_uuid: str,
    user_id: str,
    limit: int = 100
) -> List[Dict[str, Any]]:
    """Query episodes belonging to a community."""
    driver = get_neo4j_driver()

    query = """
    MATCH (ep:GraphEpisode {community_id: $community_uuid, user_id: $user_id})
    RETURN ep
    ORDER BY ep.chunk_index
    LIMIT $limit
    """

    with driver.session(database=DATABASE) as session:
        result = session.run(query, {"community_uuid": community_uuid, "user_id": user_id, "limit": limit})
        return [dict(record["ep"]) for record in result]


def query_entities_by_community(
    community_id: str,
    user_id: str,
    limit: int = 100
) -> List[Dict[str, Any]]:
    """Query entities within a community."""
    driver = get_neo4j_driver()

    query = """
    MATCH (e:GraphEntity {community_id: $community_id, user_id: $user_id})
    RETURN e
    LIMIT $limit
    """

    with driver.session(database=DATABASE) as session:
        result = session.run(query, {"community_id": community_id, "user_id": user_id, "limit": limit})
        return [dict(record["e"]) for record in result]


def query_communities_by_user(
    user_id: str,
    limit: int = 100
) -> List[Dict[str, Any]]:
    """Query all communities for a user."""
    driver = get_neo4j_driver()

    query = """
    MATCH (c:GraphCommunity {user_id: $user_id})
    RETURN c
    ORDER BY c.created_at DESC
    LIMIT $limit
    """

    with driver.session(database=DATABASE) as session:
        result = session.run(query, {"user_id": user_id, "limit": limit})
        return [dict(record["c"]) for record in result]


def query_mentions_by_episode(
    episode_ref: str,
    user_id: str,
    limit: int = 100
) -> List[Dict[str, Any]]:
    """Query all entities mentioned by an episode."""
    driver = get_neo4j_driver()

    query = """
    MATCH (ep:GraphEpisode {episode_ref: $episode_ref, user_id: $user_id})-[r:MENTIONS]->(e:GraphEntity)
    RETURN e, r
    LIMIT $limit
    """

    with driver.session(database=DATABASE) as session:
        result = session.run(query, {"episode_ref": episode_ref, "user_id": user_id, "limit": limit})
        return [{"entity": dict(record["e"]), "mentions": dict(record["r"])} for record in result]


def query_related_episodes(
    episode_ref: str,
    user_id: str,
    limit: int = 100
) -> List[Dict[str, Any]]:
    """Query episodes related to a given episode."""
    driver = get_neo4j_driver()

    query = """
    MATCH (ep:GraphEpisode {episode_ref: $episode_ref, user_id: $user_id})-[r:RELATED]->(related:GraphEpisode)
    RETURN related, r
    ORDER BY r.score DESC
    LIMIT $limit
    """

    with driver.session(database=DATABASE) as session:
        result = session.run(query, {"episode_ref": episode_ref, "user_id": user_id, "limit": limit})
        return [{"episode": dict(record["related"]), "relationship": dict(record["r"])} for record in result]


def search_entities(
    user_id: str,
    query_text: str = None,
    community_id: str = None,
    labels: List[str] = None,
    limit: int = 100
) -> List[Dict[str, Any]]:
    """
    Search entities by various criteria.

    Supports:
    - Text search (name/description contains query_text)
    - Community filtering
    - Label filtering
    """
    driver = get_neo4j_driver()

    match_clauses = ["e:GraphEntity"]
    where_clauses = ["e.user_id = $user_id"]
    params: Dict[str, Any] = {"user_id": user_id, "limit": limit}

    if query_text:
        where_clauses.append("(e.name CONTAINS $query_text OR e.description CONTAINS $query_text)")
        params["query_text"] = query_text

    if community_id:
        where_clauses.append("e.community_id = $community_id")
        params["community_id"] = community_id

    if labels:
        # Match entities that have any of the specified labels
        label_match = " OR ".join([f"e:{label}" for label in labels])
        where_clauses.append(f"({label_match})")

    where_clause = " AND ".join(where_clauses)
    query = f"""
    MATCH (e:GraphEntity)
    WHERE {where_clause}
    RETURN e
    LIMIT $limit
    """

    with driver.session(database=DATABASE) as session:
        result = session.run(query, params)
        return [dict(record["e"]) for record in result]


def get_entity_facts(
    entity_uuid: str,
    user_id: str,
    direction: str = "both",
    limit: int = 100
) -> List[Dict[str, Any]]:
    """
    Get facts (relationships) for an entity.

    Args:
        entity_uuid: Entity UUID
        user_id: User scope
        direction: "outgoing" (this entity links to others), "incoming" (others link to this), "both"
        limit: Max results
    """
    driver = get_neo4j_driver()

    params = {
        "uuid": entity_uuid,
        "user_id": user_id,
        "limit": limit
    }

    if direction == "outgoing":
        match_clause = "MATCH (e:GraphEntity {uuid: $uuid})-[r:LINKED_TO]->(other)"
        return_clause = "e, r, other"
    elif direction == "incoming":
        match_clause = "MATCH (other)-[r:LINKED_TO]->(e:GraphEntity {uuid: $uuid})"
        return_clause = "other as other_node, r, e"
    else:
        match_clause = "MATCH (e:GraphEntity {uuid: $uuid})-[r:LINKED_TO]-(other)"
        return_clause = "e, r, other"

    query = f"""
    {match_clause}
    RETURN {return_clause}
    LIMIT $limit
    """

    with driver.session(database=DATABASE) as session:
        result = session.run(query, params)
        facts = []
        for record in result:
            facts.append({
                "fact": dict(record["r"]),
                "entity": dict(record["e"]),
                "other": dict(record["other"]) if "other_node" not in record else dict(record["other_node"])
            })
        return facts


def get_community_stats(community_uuid: str, user_id: str) -> Dict[str, Any]:
    """Get statistics for a community."""
    driver = get_neo4j_driver()

    query = """
    MATCH (c:GraphCommunity {uuid: $community_uuid, user_id: $user_id})
    OPTIONAL MATCH (ep:GraphEpisode)-[:IN_COMMUNITY]->(c)
    OPTIONAL MATCH (e:GraphEntity {community_id: $community_uuid})
    RETURN c,
           count(DISTINCT ep) as episode_count,
           count(DISTINCT e) as entity_count
    """

    with driver.session(database=DATABASE) as session:
        result = session.run(query, {"community_uuid": community_uuid, "user_id": user_id})
        record = result.single()
        if record:
            return {
                "community": dict(record["c"]),
                "episode_count": record["episode_count"],
                "entity_count": record["entity_count"]
            }
        return None


def delete_episode(episode_ref: str, user_id: str) -> bool:
    """Delete an episode and its relationships."""
    driver = get_neo4j_driver()

    query = """
    MATCH (ep:GraphEpisode {episode_ref: $episode_ref, user_id: $user_id})
    DETACH DELETE ep
    """

    with driver.session(database=DATABASE) as session:
        result = session.run(query, {"episode_ref": episode_ref, "user_id": user_id})
        return True


def delete_community(community_uuid: str, user_id: str) -> bool:
    """Delete a community (does not delete associated episodes)."""
    driver = get_neo4j_driver()

    query = """
    MATCH (c:GraphCommunity {uuid: $community_uuid, user_id: $user_id})
    DETACH DELETE c
    """

    with driver.session(database=DATABASE) as session:
        result = session.run(query, {"community_uuid": community_uuid, "user_id": user_id})
        return True


def update_episode_community(
    episode_ref: str,
    user_id: str,
    community_uuid: str
) -> Optional[Dict[str, Any]]:
    """Update episode's community assignment."""
    driver = get_neo4j_driver()

    query = """
    MATCH (ep:GraphEpisode {episode_ref: $episode_ref, user_id: $user_id})
    SET ep.community_id = $community_uuid,
        ep.updated_at = $updated_at
    RETURN ep
    """

    with driver.session(database=DATABASE) as session:
        result = session.run(query, {
            "episode_ref": episode_ref,
            "user_id": user_id,
            "community_uuid": community_uuid,
            "updated_at": datetime.utcnow().isoformat()
        })
        record = result.single()
        return dict(record["ep"]) if record else None


def update_community_episode_count(community_uuid: str, user_id: str) -> bool:
    """Recalculate and update the episode_count for a community."""
    driver = get_neo4j_driver()

    query = """
    MATCH (c:GraphCommunity {uuid: $community_uuid, user_id: $user_id})
    OPTIONAL MATCH (ep:GraphEpisode)-[:IN_COMMUNITY]->(c)
    SET c.episode_count = count(DISTINCT ep),
        c.updated_at = $updated_at
    RETURN c
    """

    with driver.session(database=DATABASE) as session:
        result = session.run(query, {
            "community_uuid": community_uuid,
            "user_id": user_id,
            "updated_at": datetime.utcnow().isoformat()
        })
        return result.single() is not None
