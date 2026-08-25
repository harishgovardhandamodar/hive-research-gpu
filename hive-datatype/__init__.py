"""
hive-datatype — Core data model for HiveMind knowledge graphs.

Provides self-contained data classes, validation, and serialization
for the four node types (paper, graph_paper, concept, graph_ref)
and the eleven valid edge relations.
"""

from .hive_datatype import (
    VALID_RELATIONS,
    LINEAGE_RELATIONS,
    D3_GROUP,
    NodeType,
    Relation,
    Node,
    Edge,
    HiveStats,
    HiveGraph,
    MetaNode,
    MetaEdge,
    MetaGraph,
    FederationStats,
    aggregate_stats,
    build_meta_graph,
    validate_relation,
)
