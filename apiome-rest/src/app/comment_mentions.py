"""Server-side ``@name`` mention parsing for comments — COL-1.1 (#4513).

A comment's ``mentions`` column is the source of truth for who gets notified (COL-3.1) and for the
"mentions me" filter, so the server — never the client — decides which members a body mentions.
This module is pure: it takes the Markdown body and the tenant's members and returns user ids.

**What counts as a mention.** An ``@`` followed by a handle, where the ``@`` starts the text or
follows something that is not part of a word, an address, or a URL — so ``jane@example.com`` and
``https://medium.com/@jane`` mention nobody. A handle is word characters with ``.``, ``+``, and
``-`` allowed inside it (``@jane.doe``), and may be a whole email address (``@jane@example.com``).
Trailing sentence punctuation is not part of the handle: ``thanks @jane.`` mentions ``jane``.
Tokens inside fenced code blocks and inline code spans are ignored, and ``\\@jane`` is an escaped
literal, not a mention.

**How a handle resolves.** Matching is case-insensitive. Each member answers to three handles:

* their full email address (``jane.doe@example.com``) — unique per user, the unambiguous spelling;
* their email local part (``jane.doe``);
* their display name with everything but handle characters removed (``Jane Doe`` → ``janedoe``).

A handle that matches **exactly one** member resolves to that member. A handle that matches several
members (two people named "Alex", say) resolves to nobody and is reported as ambiguous — notifying
the wrong person is worse than notifying no one, and the full email is always available to
disambiguate. A handle that matches nobody is reported as unresolved.

Resolved ids are de-duplicated in order of first mention and capped at :data:`MAX_MENTIONS`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Set

__all__ = [
    "MAX_MENTIONS",
    "MentionCandidate",
    "MentionResolution",
    "extract_mention_handles",
    "member_handles",
    "resolve_mentions",
]

#: The most distinct members one comment may mention. Mirrors the
#: ``comments_mentions_cardinality_check`` constraint in apiome-db V259.
MAX_MENTIONS = 50

#: A fenced code block: a run of three or more backticks or tildes opening a line, up to a closing
#: fence of the same run (or the end of the body, which is how Markdown treats an unclosed fence).
_FENCED_BLOCK = re.compile(
    r"^[ \t]{0,3}(?P<fence>`{3,}|~{3,})[^\n]*\n.*?(?:^[ \t]{0,3}(?P=fence)[ \t]*$|\Z)",
    re.MULTILINE | re.DOTALL,
)

#: An inline code span: a backtick run, content, and the same-length run closing it.
_INLINE_CODE = re.compile(r"(?<!`)(?P<ticks>`+)(?!`).+?(?<!`)(?P=ticks)(?!`)", re.DOTALL)

#: A mention token. The look-behind rejects an ``@`` inside a word, an email address, a URL path,
#: or after a Markdown escape. The handle must end on a word character, so trailing sentence
#: punctuation is left out; the optional second part admits a whole email address.
_MENTION = re.compile(
    r"(?<![\w.%+\-@/\\])@(?P<handle>\w(?:[\w.+\-]*\w)?(?:@\w(?:[\w\-]*\w)?(?:\.\w(?:[\w\-]*\w)?)+)?)"
)

#: Characters a display-name handle keeps; everything else (spaces, apostrophes) is dropped.
_NAME_HANDLE_DROP = re.compile(r"[^\w.+\-]")

#: The longest handle worth looking up (an email address is at most 254 characters).
_MAX_HANDLE_LENGTH = 254


@dataclass(frozen=True)
class MentionCandidate:
    """A tenant member a mention may resolve to.

    Attributes:
        user_id: The member's user id.
        name: Their display name, if any.
        email: Their email address, if any.
    """

    user_id: str
    name: Optional[str] = None
    email: Optional[str] = None


@dataclass(frozen=True)
class MentionResolution:
    """The outcome of resolving a body's mentions.

    Attributes:
        user_ids: Distinct resolved member ids, in order of first mention, capped at
            :data:`MAX_MENTIONS`.
        unresolved: Distinct handles (lower-cased) that matched no member.
        ambiguous: Distinct handles (lower-cased) that matched more than one member.
    """

    user_ids: List[str] = field(default_factory=list)
    unresolved: List[str] = field(default_factory=list)
    ambiguous: List[str] = field(default_factory=list)


def _strip_code(body: str) -> str:
    """Blank out fenced code blocks and inline code spans, where an ``@`` is never a mention.

    Args:
        body: The Markdown body.

    Returns:
        The body with every code region replaced by spaces of the same length, so nothing outside
        a code region changes position or merges with a neighbour.
    """
    blank = lambda match: " " * len(match.group(0))  # noqa: E731 - tiny local substitution
    without_blocks = _FENCED_BLOCK.sub(blank, body)
    return _INLINE_CODE.sub(blank, without_blocks)


def extract_mention_handles(body: str) -> List[str]:
    """Return the distinct mention handles in a Markdown body, lower-cased, in order.

    Args:
        body: The Markdown body.

    Returns:
        Each distinct handle once, in order of first appearance. Code regions and escaped ``\\@``
        are ignored, and a handle longer than an email address can be is skipped.
    """
    seen: Set[str] = set()
    handles: List[str] = []
    for match in _MENTION.finditer(_strip_code(body or "")):
        handle = match.group("handle").casefold()
        if len(handle) > _MAX_HANDLE_LENGTH or handle in seen:
            continue
        seen.add(handle)
        handles.append(handle)
    return handles


def member_handles(candidate: MentionCandidate) -> Set[str]:
    """Return every handle a member answers to, lower-cased.

    Args:
        candidate: The member.

    Returns:
        Their full email, their email local part, and their compacted display name — whichever of
        those are non-empty.
    """
    handles: Set[str] = set()
    email = (candidate.email or "").strip().casefold()
    if email:
        handles.add(email)
        local = email.split("@", 1)[0]
        if local:
            handles.add(local)
    name = _NAME_HANDLE_DROP.sub("", (candidate.name or "").casefold()).strip(".+-")
    if name:
        handles.add(name)
    return handles


def resolve_mentions(body: str, members: Iterable[MentionCandidate]) -> MentionResolution:
    """Resolve the ``@name`` tokens in a body against a tenant's members.

    Args:
        body: The Markdown body.
        members: The members a mention may resolve to.

    Returns:
        The resolved ids plus the handles that matched nobody or more than one member.
    """
    handles = extract_mention_handles(body)
    if not handles:
        return MentionResolution()

    index: Dict[str, Set[str]] = {}
    for member in members:
        user_id = str(member.user_id or "").strip()
        if not user_id:
            continue
        for handle in member_handles(member):
            index.setdefault(handle, set()).add(user_id)

    user_ids: List[str] = []
    unresolved: List[str] = []
    ambiguous: List[str] = []
    for handle in handles:
        matches = index.get(handle, set())
        if len(matches) == 1:
            (user_id,) = matches
            if user_id not in user_ids and len(user_ids) < MAX_MENTIONS:
                user_ids.append(user_id)
        elif matches:
            ambiguous.append(handle)
        else:
            unresolved.append(handle)
    return MentionResolution(user_ids=user_ids, unresolved=unresolved, ambiguous=ambiguous)
