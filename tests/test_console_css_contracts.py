from __future__ import annotations

import re
from pathlib import Path

CSS_PATH = Path(__file__).resolve().parents[1] / "web" / "src" / "styles.css"


def _css_text() -> str:
    return CSS_PATH.read_text(encoding="utf-8")


def _rule_body(css: str, selector: str) -> str:
    match = re.search(rf"{re.escape(selector)}\s*\{{(?P<body>[^}}]+)\}}", css)
    assert match is not None, f"Missing CSS rule for {selector}"
    return match.group("body")


def _combined_rule_body(css: str, selectors: list[str]) -> str:
    pattern = r",\s*".join(re.escape(selector) for selector in selectors)
    match = re.search(rf"{pattern}\s*\{{(?P<body>[^}}]+)\}}", css)
    assert match is not None, f"Missing CSS rule for {', '.join(selectors)}"
    return match.group("body")


def test_repos_table_action_column_has_right_breathing_room() -> None:
    css = _css_text()
    scroll_body = _rule_body(css, ".repos-table-scroll")
    action_body = _combined_rule_body(
        css,
        [".repos-table th:nth-child(7)", ".repos-table td:nth-child(7)"],
    )

    assert "padding-right: var(--space-3);" in scroll_body
    assert "padding-right: var(--space-2);" in action_body


def test_repos_table_name_column_absorbs_desktop_width() -> None:
    css = _css_text()
    table_body = _rule_body(css, ".repos-table")
    name_body = _rule_body(css, ".repos-table td:nth-child(1)")
    truncation_body = _combined_rule_body(
        css,
        [
            ".repos-table td:nth-child(1) .link-button",
            ".repos-table td:nth-child(1) .path-cell",
        ],
    )

    assert "width: 100%;" in table_body
    assert "table-layout: fixed;" in table_body
    assert "overflow: hidden;" in name_body
    assert "max-width: 100%;" in truncation_body
    assert "text-overflow: ellipsis;" in truncation_body
    assert "white-space: nowrap;" in truncation_body
