"""Versioned knowledge base with lightweight keyword retrieval.

The corpus is small (project docs + FAQ), so scored keyword retrieval is the
right tool; pgvector in the existing PostgreSQL is the upgrade path if the
corpus grows — never a separate vector database.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

KB_VERSION = "kb-v1"

_FAQ: list[tuple[str, str]] = [
    ("Why didn't the bot trade today?",
     "The bot only trades when a strategy signal passes every check: market "
     "regime, expected profit vs costs, spread, liquidity, session hours and "
     "all risk limits. Most days most signals fail at least one check — that "
     "protects your balance. See the 'Why didn't it trade?' dashboard panel."),
    ("Is profit guaranteed?",
     "No. No strategy or bot can guarantee profit. This application is built "
     "to control losses, measure honestly, and skip bad trades — losing days "
     "still happen."),
    ("What is paper trading?",
     "A simulation using real live prices and realistic fees, spread and "
     "slippage, but no real money. It builds evidence about whether a "
     "strategy deserves real money — most don't."),
    ("How do I enable live trading?",
     "You can't from the app. Live trading requires ~90 days of paper "
     "evidence, security and reliability drills, and a signed owner approval "
     "— then a separate multi-step configuration outside the UI. This is "
     "deliberate."),
    ("What do the signal statuses mean?",
     "Strong Buy/Buy/Hold/Sell/Strong Sell summarise the combined score of "
     "several indicators and strategies. No Trade means a safety check "
     "failed; Risk Blocked means a risk limit vetoed; Data Unavailable means "
     "the market feed is stale. They are decision support, not advice."),
    ("What fees does the bot pay?",
     "Binance charges a fee per trade (typically 0.1% without discounts). "
     "The bot also models spread and slippage. Every backtest, paper trade "
     "and report includes these costs — never gross numbers."),
]


@dataclass
class KnowledgeBase:
    docs_dir: Path | None = None
    _chunks: list[dict[str, Any]] = field(default_factory=list)

    def load(self) -> None:
        from cryptobot.ai.crypto_kb import as_chunks

        for question, answer in _FAQ:
            self._chunks.append({"doc": "faq", "version": KB_VERSION,
                                 "title": question, "text": answer})
        self._chunks.extend(as_chunks())     # curated crypto knowledge corpus
        if self.docs_dir and self.docs_dir.exists():
            for path in sorted(self.docs_dir.glob("*.md")):
                text = path.read_text(encoding="utf-8", errors="ignore")
                for section in re.split(r"\n(?=#{1,3} )", text):
                    title = section.splitlines()[0].lstrip("# ").strip() if section else ""
                    body = section.strip()
                    if len(body) > 100:
                        self._chunks.append({
                            "doc": path.stem, "version": KB_VERSION,
                            "title": title, "text": body[:1500],
                        })

    def search(self, query: str, top_k: int = 3) -> dict[str, Any]:
        terms = [t for t in re.findall(r"[a-z0-9]+", query.lower()) if len(t) > 2]
        if not terms or not self._chunks:
            return {"results": [], "kb_version": KB_VERSION,
                    "note": "no matching documentation found"}
        scored: list[tuple[float, dict[str, Any]]] = []
        for chunk in self._chunks:
            haystack = (chunk["title"] + " " + chunk["text"]).lower()
            score = sum(haystack.count(t) for t in terms)
            score += sum(3 for t in terms if t in chunk["title"].lower())
            if score > 0:
                scored.append((score, chunk))
        scored.sort(key=lambda s: -s[0])
        return {
            "results": [
                {"doc": c["doc"], "version": c["version"], "title": c["title"],
                 "text": c["text"]}
                for _, c in scored[:top_k]
            ],
            "kb_version": KB_VERSION,
        }
