"""Graph 声明与拓扑校验测试。"""

import pytest

from agentorchestra.orchestration import FunctionalNode, Graph
from agentorchestra.orchestration.graph import NodeOutput


def _dummy_factory():
    return None  # 不在 validate 阶段真正创建


def _make_node(name):
    n = FunctionalNode(lambda msg, ctx: NodeOutput.ok(result=name))
    return n


def test_add_node_and_edge():
    g = Graph()
    g.add_node("a", _make_node("a"))
    g.add_node("b", _make_node("b"))
    g.add_edge("a", "b")
    assert g.nodes() == ["a", "b"]
    assert g.validate() == []


def test_validate_unknown_target():
    """add_edge 已对未知节点抛错；validate 兜底检出自环等结构性错误。"""
    g = Graph()
    g.add_node("a", _make_node("a"))
    # 直接塞内部边绕过 add_edge 校验（模拟外部篡改）
    g._edges["a"].append(__import__(
        "agentorchestra.orchestration.graph", fromlist=["Edge"]).Edge("a", "ghost"))
    errs = g.validate()
    assert any("ghost" in e for e in errs)


def test_validate_self_loop():
    g = Graph()
    g.add_node("a", _make_node("a"))
    g.add_edge("a", "a")
    errs = g.validate()
    assert any("自环" in e for e in errs)


def test_add_edge_unknown_node_raises():
    g = Graph()
    g.add_node("a", _make_node("a"))
    with pytest.raises(ValueError):
        g.add_edge("a", "ghost")
    with pytest.raises(ValueError):
        g.add_edge("ghost", "a")


def test_conditional_edge_stored():
    g = Graph()
    g.add_node("a", _make_node("a"))
    g.add_node("b", _make_node("b"))
    g.add_edge("a", "b", when="approved")
    edges = g.outgoing("a")
    assert len(edges) == 1
    assert edges[0].when == "approved"
