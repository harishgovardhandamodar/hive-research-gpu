import sys
from pathlib import Path

try:
    from hive_datatype import Node, Edge, HiveGraph, NodeType
except ImportError:
    _candidates = [
        Path(__file__).resolve().parent.parent / "hive-datatype",
        Path(__file__).resolve().parent.parent.parent / "hive-datatype",
    ]
    for _p in _candidates:
        if (_p / "hive_datatype.py").exists():
            sys.path.insert(0, str(_p))
            break

try:
    from hive_datatype import Node, Edge, HiveGraph, NodeType  # noqa: F811
except ImportError as _e:  # pragma: no cover - environment problem
    raise ImportError(
        "hive-datatype not found. Install it or keep the bundled "
        "hive-datatype/ directory next to hive_research/."
    ) from _e
