"""Neo4j singleton driver client."""

from __future__ import annotations

import logging
from typing import Optional

from neo4j import Driver, GraphDatabase

from app.core.config import settings

logger = logging.getLogger(__name__)

_driver: Optional[Driver] = None


def get_neo4j_driver() -> Optional[Driver]:
    """Return the global Neo4j driver singleton."""
    global _driver
    if _driver is None:
        neo4j_uri = (settings.NEO4J_URI or "").strip()
        if neo4j_uri:
            try:
                _driver = GraphDatabase.driver(
                    neo4j_uri,
                    auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
                )
                logger.info("Neo4j driver initialized")
            except Exception as e:
                logger.error(f"Failed to initialize Neo4j driver: {e}")
    return _driver


def close_neo4j_driver() -> None:
    """Close the global Neo4j driver."""
    global _driver
    if _driver:
        try:
            _driver.close()
            logger.info("Neo4j driver closed")
        except Exception as e:
            logger.warning(f"Error closing Neo4j driver: {e}")
        finally:
            _driver = None
