"""MCP catalog auto-categorization heuristics — suggest-only (V2-MCP-23.4 / MCAT-9.4, #3694).

Filing every cataloged server under a category by hand (MCAT-9.3, :mod:`app.mcp_categorization`) does
not scale. This module is the pure, DB-free half of the answer: it reads a server's declared surface —
its **tool names and descriptions**, plus the server's own name, title and instructions — and ranks
the categories in the tenant's lookup by how well they fit.

Design notes:

* **Suggest-only.** Nothing here writes. A suggestion is a ranked list with the matched keywords that
  explain it; a person confirms it by setting the endpoint's ``category`` with the existing
  ``PATCH /v1/mcp/{tenant}/endpoints/{id}``. The suggestion routes never apply a category.
* **Keyword lexicon per built-in category.** Each built-in category has a short list of signal words
  (``sql``, ``postgres`` → *Databases*; ``email``, ``slack`` → *Communication*). Tenant categories are
  matched on the words of their own slug and label, so a ``weather`` category catches ``get_weather``.
* **Where a word appears matters.** A word in a tool's *name* is strong evidence, in its *title* less,
  in its *description* least; the server's name and title count like a tool name. Each word counts at
  most once per field, so one long description cannot outvote the tool names.
* **No signal, no suggestion.** Below :data:`MIN_SUGGESTION_SCORE` the result is empty rather than a
  guess, and ``other`` is never suggested — it is a choice a person makes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .mcp_categorization import BUILTIN_CATEGORIES
from .mcp_client.normalize import ITEM_TYPE_TOOL

# --- Lexicon ------------------------------------------------------------------------------------

#: Signal words per built-in category slug, written in the singular (tokens are singularized the same
#: way before matching, see :func:`_singular`). ``other`` has none on purpose.
CATEGORY_KEYWORDS: Mapping[str, Tuple[str, ...]] = {
    "developer-tools": (
        "git", "github", "gitlab", "bitbucket", "commit", "branch", "merge", "repo", "repository",
        "code", "lint", "linter", "compile", "compiler", "debug", "debugger", "npm", "pypi",
        "package", "snippet", "refactor", "ide", "terminal", "shell", "diff", "pr",
    ),
    "data-analytics": (
        "analytic", "metric", "dashboard", "report", "chart", "insight", "aggregate", "statistic",
        "kpi", "bigquery", "snowflake", "warehouse", "etl", "dataset", "visualization", "trend",
        "forecast", "funnel", "cohort",
    ),
    "databases": (
        "sql", "database", "db", "table", "row", "column", "postgres", "postgresql", "mysql",
        "sqlite", "mongodb", "mongo", "redis", "dynamodb", "cassandra", "supabase", "query",
        "insert", "upsert",
    ),
    "files-storage": (
        "file", "folder", "directory", "upload", "download", "storage", "bucket", "s3", "blob",
        "drive", "dropbox", "attachment", "filesystem",
    ),
    "search-web": (
        "search", "web", "browse", "browser", "crawl", "crawler", "scrape", "scraper", "fetch",
        "url", "webpage", "website", "html", "google", "bing", "serp",
    ),
    "productivity": (
        "calendar", "event", "meeting", "task", "todo", "note", "notion", "reminder", "schedule",
        "document", "spreadsheet", "sheet", "jira", "trello", "asana", "linear", "ticket", "project",
    ),
    "communication": (
        "email", "mail", "message", "slack", "chat", "channel", "notify", "notification", "sms",
        "discord", "inbox", "reply", "teams", "whatsapp", "telegram",
    ),
    "cloud-infrastructure": (
        "aws", "gcp", "azure", "kubernetes", "k8s", "pod", "cluster", "container", "docker",
        "deploy", "deployment", "instance", "vm", "terraform", "lambda", "cloudflare", "dns",
        "infrastructure", "ec2", "helm",
    ),
    "finance-commerce": (
        "payment", "invoice", "charge", "refund", "stripe", "order", "cart", "checkout", "product",
        "price", "subscription", "billing", "transaction", "balance", "currency", "shopify",
        "stock", "ledger",
    ),
    "ai-ml": (
        "embedding", "llm", "inference", "vector", "train", "training", "finetune", "classifier",
        "sentiment", "transcribe", "transcription", "ocr", "huggingface", "ml", "neural",
        "predict", "prediction",
    ),
    "security": (
        "secret", "vulnerability", "cve", "password", "credential", "encrypt", "decrypt",
        "encryption", "threat", "malware", "firewall", "certificate", "iam", "siem", "pentest",
        "sast", "compliance", "audit",
    ),
}

#: Weight of one matched word, by where it appeared.
WEIGHT_TOOL_NAME: int = 3
WEIGHT_TOOL_TITLE: int = 2
WEIGHT_TOOL_DESCRIPTION: int = 1
WEIGHT_SERVER_NAME: int = 3
WEIGHT_SERVER_INSTRUCTIONS: int = 1

#: Least total score a category needs before it is suggested (one tool-name hit).
MIN_SUGGESTION_SCORE: int = WEIGHT_TOOL_NAME

#: Score at which a category's evidence counts as "strong" for the confidence calculation.
STRONG_SCORE: int = 12

#: Most suggestions returned per server.
MAX_SUGGESTIONS: int = 3

#: Most tools read per server, so a very large surface stays a bounded amount of work.
MAX_TOOLS_SCANNED: int = 200

#: Shortest tenant-category word used as a keyword (drops ``a``, ``of``, ``&`` …).
_MIN_TENANT_KEYWORD_LENGTH: int = 3

#: Category slugs that are never suggested.
_NEVER_SUGGESTED = frozenset({"other"})

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


# --- Results ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class CategorySuggestion:
    """One ranked category suggestion for a server.

    Attributes:
        slug: The category's slug (built-in or tenant).
        label: The category's display label.
        builtin: Whether it is a built-in category.
        score: Weighted keyword evidence (higher is better).
        confidence: ``0``–``1``; the category's share of all evidence, scaled down when the evidence
            itself is thin (see :func:`_confidence`).
        matched_keywords: The keywords that matched, most evidence first.
    """

    slug: str
    label: str
    builtin: bool
    score: int
    confidence: float
    matched_keywords: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        """Return the suggestion as a plain dict for the wire model."""
        return {
            "slug": self.slug,
            "label": self.label,
            "builtin": self.builtin,
            "score": self.score,
            "confidence": self.confidence,
            "matched_keywords": list(self.matched_keywords),
        }


# --- Tokenizing ---------------------------------------------------------------------------------


def _singular(word: str) -> str:
    """Fold a simple English plural to its singular (``queries`` → ``query``, ``files`` → ``file``).

    Deliberately crude: it only has to make a token and a lexicon word meet, and both pass through it.
    """
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def tokenize(text: Optional[str]) -> List[str]:
    """Split identifier-ish or prose text into lowercase, singularized words.

    ``createPullRequest``, ``create_pull_request``, ``create-pull-request`` and
    ``"Create a pull request"`` all yield ``["create", "pull", "request"]`` (articles included —
    the lexicon is the filter, not a stop list).

    Args:
        text: Any text; ``None`` or blank yields ``[]``.

    Returns:
        The words in order of appearance (duplicates kept).
    """
    if not text:
        return []
    spaced = _CAMEL_BOUNDARY.sub(" ", str(text))
    return [_singular(w) for w in _NON_ALNUM.split(spaced.lower()) if w]


# --- Vocabulary ---------------------------------------------------------------------------------


def builtin_vocabulary() -> List[Dict[str, Any]]:
    """The built-in categories as lookup-style rows (``slug`` / ``label`` / ``builtin``).

    Used when the caller has no tenant lookup at hand (e.g. tests, offline use).
    """
    return [{"slug": slug, "label": label, "builtin": True} for slug, label in BUILTIN_CATEGORIES]


def category_keywords(category: Mapping[str, Any]) -> Tuple[str, ...]:
    """Return the keywords a category is matched on.

    A built-in category uses its :data:`CATEGORY_KEYWORDS` entry; any other category uses the words of
    its slug and label (at least :data:`_MIN_TENANT_KEYWORD_LENGTH` letters), so a tenant category
    labelled ``"Weather & climate"`` matches ``weather`` and ``climate``.

    Args:
        category: A lookup row with ``slug``, ``label`` and optionally ``builtin``.

    Returns:
        The distinct keywords, in a stable order.
    """
    slug = str(category.get("slug") or "")
    if category.get("builtin") and slug in CATEGORY_KEYWORDS:
        # Fold the lexicon the same way tokens are folded, so ``postgres`` meets ``postgre``.
        return tuple(dict.fromkeys(_singular(w) for w in CATEGORY_KEYWORDS[slug]))
    words: List[str] = []
    for word in tokenize(slug) + tokenize(str(category.get("label") or "")):
        if len(word) >= _MIN_TENANT_KEYWORD_LENGTH and word not in words:
            words.append(word)
    return tuple(words)


# --- Scoring ------------------------------------------------------------------------------------


def _evidence_fields(
    server: Mapping[str, Any], tools: Sequence[Mapping[str, Any]]
) -> List[Tuple[int, List[str]]]:
    """List every field the heuristic reads as ``(weight, words)``.

    Server identity (``name`` / ``server_name`` / ``server_title`` / ``instructions``) and, for each of
    the first :data:`MAX_TOOLS_SCANNED` tools, its ``name`` / ``title`` / ``description``.
    """
    fields: List[Tuple[int, List[str]]] = []
    for key in ("name", "server_name", "server_title"):
        fields.append((WEIGHT_SERVER_NAME, tokenize(server.get(key))))
    fields.append((WEIGHT_SERVER_INSTRUCTIONS, tokenize(server.get("instructions"))))
    for tool in list(tools)[:MAX_TOOLS_SCANNED]:
        fields.append((WEIGHT_TOOL_NAME, tokenize(tool.get("name"))))
        fields.append((WEIGHT_TOOL_TITLE, tokenize(tool.get("title"))))
        fields.append((WEIGHT_TOOL_DESCRIPTION, tokenize(tool.get("description"))))
    return [(w, words) for w, words in fields if words]


def _confidence(score: int, total: int) -> float:
    """Confidence in ``0``–``1``: the category's share of all evidence, times how strong it is.

    A category that holds all the evidence but only from one weak hit is not a confident call, so the
    share is scaled by ``min(1, score / STRONG_SCORE)``. Rounded to two places.
    """
    if score <= 0 or total <= 0:
        return 0.0
    share = score / total
    strength = min(1.0, score / STRONG_SCORE)
    return round(share * strength, 2)


def suggest_categories(
    server: Mapping[str, Any],
    tools: Sequence[Mapping[str, Any]],
    categories: Optional[Sequence[Mapping[str, Any]]] = None,
    *,
    limit: int = MAX_SUGGESTIONS,
) -> List[CategorySuggestion]:
    """Rank the categories that fit a server's declared surface. Pure; never writes.

    Args:
        server: Server identity — any of ``name`` (the catalog entry's name), ``server_name``,
            ``server_title`` and ``instructions``. Missing keys are skipped.
        tools: The server's tools, each with ``name`` and optionally ``title`` / ``description``
            (the ``mcp_capability_items`` rows of type ``tool`` fit as-is).
        categories: The tenant's lookup rows (``slug`` / ``label`` / ``builtin``); defaults to the
            built-in vocabulary. ``other`` is never suggested.
        limit: Most suggestions to return.

    Returns:
        Up to ``limit`` suggestions, best first (score, then lookup order). Empty when no category
        reaches :data:`MIN_SUGGESTION_SCORE`.
    """
    vocabulary = list(categories) if categories is not None else builtin_vocabulary()
    fields = _evidence_fields(server, tools)

    scored: List[Tuple[int, int, CategorySuggestion]] = []
    for order, category in enumerate(vocabulary):
        slug = str(category.get("slug") or "")
        if not slug or slug in _NEVER_SUGGESTED:
            continue
        keywords = set(category_keywords(category))
        if not keywords:
            continue
        score = 0
        hits: Dict[str, int] = {}
        for weight, words in fields:
            for word in set(words) & keywords:
                score += weight
                hits[word] = hits.get(word, 0) + weight
        if score < MIN_SUGGESTION_SCORE:
            continue
        matched = sorted(hits, key=lambda w: (-hits[w], w))
        scored.append(
            (
                score,
                order,
                CategorySuggestion(
                    slug=slug,
                    label=str(category.get("label") or slug),
                    builtin=bool(category.get("builtin")),
                    score=score,
                    confidence=0.0,
                    matched_keywords=matched,
                ),
            )
        )

    total = sum(s for s, _, _ in scored)
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [
        CategorySuggestion(
            slug=s.slug,
            label=s.label,
            builtin=s.builtin,
            score=s.score,
            confidence=_confidence(s.score, total),
            matched_keywords=s.matched_keywords,
        )
        for _, _, s in scored[: max(0, limit)]
    ]


def tools_from_capability_items(items: Iterable[Mapping[str, Any]]) -> List[Mapping[str, Any]]:
    """Keep the ``tool`` rows of a snapshot's ``mcp_capability_items`` (resources/prompts dropped)."""
    return [item for item in items if item.get("item_type") == ITEM_TYPE_TOOL]


__all__ = [
    "CATEGORY_KEYWORDS",
    "CategorySuggestion",
    "MAX_SUGGESTIONS",
    "MAX_TOOLS_SCANNED",
    "MIN_SUGGESTION_SCORE",
    "STRONG_SCORE",
    "builtin_vocabulary",
    "category_keywords",
    "suggest_categories",
    "tokenize",
    "tools_from_capability_items",
]
