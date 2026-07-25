"""Web search — Jarvis's first real action. Read-only, so no confirmation.

Keyless DuckDuckGo (ddgs) for v-now; swap to a hosted search API later behind
this same Tool. Proves the tool-use loop end-to-end.
"""

from __future__ import annotations

from .base import Tool


class WebSearch(Tool):
    name = "web_search"
    description = (
        "Search the web for current, factual, or recent information you are not "
        "sure about or that post-dates your knowledge. Use for news, prices, "
        "addresses, live facts. Returns the top results as text."
    )
    input_schema = {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "the search query"}},
        "required": ["query"],
    }
    needs_confirm = False

    def execute(self, query: str = "", **_) -> str:
        query = query.strip()
        if not query:
            return "No query provided."
        try:
            from ddgs import DDGS

            results = list(DDGS().text(query, max_results=5))
        except Exception as e:  # network/provider hiccup — tell the model, don't crash
            return f"Search failed: {e}"
        if not results:
            return "No results found."
        lines = []
        for r in results:
            title = r.get("title", "").strip()
            body = (r.get("body") or "").strip()
            lines.append(f"- {title}: {body}")
        return "\n".join(lines)
