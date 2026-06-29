from __future__ import annotations

from typing import Any, cast

from attractor_pipeline.graph import Edge, Graph, Node
from attractor_pipeline.parser import parse_dot
from attractor_pipeline.validation import Severity, validate


def rules_for(dot: str) -> dict[str, Severity]:
    graph = parse_dot(dot)
    return {diagnostic.rule: diagnostic.severity for diagnostic in validate(graph)}


def test_valid_graph_has_no_diagnostics() -> None:
    diagnostics = validate(
        parse_dot(
            """
            digraph Valid {
              graph [goal="Ship"]
              start [shape=Mdiamond]
              task [shape=box, prompt="Do work"]
              done [shape=Msquare]
              start -> task -> done
            }
            """
        )
    )

    assert diagnostics == []


def test_missing_start_and_exit_are_errors() -> None:
    rule_map = rules_for(
        """
        digraph Missing {
          task [shape=box, prompt="Do work"]
        }
        """
    )

    assert rule_map["R01"] == Severity.ERROR
    assert rule_map["R02"] == Severity.ERROR


def test_unreachable_node_and_missing_prompt_are_warnings() -> None:
    rule_map = rules_for(
        """
        digraph Warnings {
          graph [goal="Warn"]
          start [shape=Mdiamond]
          task [shape=box]
          orphan [shape=box]
          done [shape=Msquare]
          start -> task -> done
        }
        """
    )

    assert rule_map["R05"] == Severity.WARNING
    assert rule_map["R13"] == Severity.WARNING


def test_missing_goal_is_info() -> None:
    rule_map = rules_for(
        """
        digraph Info {
          start [shape=Mdiamond]
          done [shape=Msquare]
          start -> done
        }
        """
    )

    assert rule_map["R12"] == Severity.INFO


def test_invalid_condition_is_error() -> None:
    graph = Graph(name="BadCondition", goal="Check")
    graph.nodes["start"] = Node(id="start", shape="Mdiamond")
    graph.nodes["done"] = Node(id="done", shape="Msquare")
    graph.edges.append(Edge(source="start", target="done", condition=cast(Any, 1)))
    rule_map = {diagnostic.rule: diagnostic.severity for diagnostic in validate(graph)}

    assert rule_map["R14"] == Severity.ERROR


def test_manager_without_child_graph_is_error() -> None:
    rule_map = rules_for(
        """
        digraph Manager {
          graph [goal="Check"]
          start [shape=Mdiamond]
          manager [shape=hexagon]
          done [shape=Msquare]
          start -> manager -> done
        }
        """
    )

    assert rule_map["R15"] == Severity.ERROR
