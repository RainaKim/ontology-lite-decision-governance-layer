"""
app.graph — graph storage layer.

Exports the base interface and both implementations so callers can import
from a single location:

    from app.graph import BaseGraphRepository, InMemoryGraphRepository, Neo4jGraphRepository
"""

from app.graph.base import BaseGraphRepository
from app.graph.in_memory_repository import InMemoryGraphRepository
from app.graph.neo4j_repository import Neo4jGraphRepository

__all__ = [
    "BaseGraphRepository",
    "InMemoryGraphRepository",
    "Neo4jGraphRepository",
]
