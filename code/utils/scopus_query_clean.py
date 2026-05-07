"""
scopus_query_clean.py
Sanitise Aurora SDG composed queries for the current Scopus parser.

Scopus (2024+) rejects wildcards (*) inside quoted strings, which
causes the entire TITLE-ABS-KEY clause to return zero results.
This module provides clean_for_scopus() which applies four rules in
sequence to remove or unquote problematic wildcard patterns while
preserving all Boolean operators, proximity operators, country names,
year/doctype filters, and unquoted trailing wildcards.

Rules applied in order:
  A  - "word*"     -> word*        (unquote single-token wildcard)
  B  - "w1 w2*"   -> "w1 w2"     (strip trailing wildcard from phrase)
  C  - {phrase*}   -> {phrase}     (strip wildcard from exact-match braces)
  D  - *word       -> word         (remove unsupported leading wildcard)
  B+ - "w1* w2"   -> "w1 w2"     (cleanup: infix wildcard in quoted phrase)

Root cause of B+ restriction:
  The naive r'"([^"]*)\\*([^"]*)"' pattern is intentionally NOT used for B+.
  Because [^"]* matches the asterisk itself, that pattern can span from the
  closing " of one quoted token across unquoted wildcards (produced by Rule A)
  to the opening " of the next quoted token, thereby erasing wildcards that
  were legitimately converted by Rule A.  The restrictive _RE_BPLUS below
  only matches genuine multi-word quoted phrases by requiring all characters
  inside the quotes to be word chars, spaces, hyphens, or apostrophes --
  never Scopus operator chars like W, /, (, ), etc.
"""

import re
from typing import Dict, List, Tuple


# ── Compiled patterns ─────────────────────────────────────────────────────────

# Rule A: "word*" or "hyphen-word*" -> word*
# Handles plain words AND hyphenated tokens like "socio-economic*".
# Unquoting lets Scopus treat the wildcard as an unquoted suffix search.
_RE_A = re.compile(r'"([A-Za-z][A-Za-z0-9\-]*\*)"')

# Rule B: "word1 word2*" (any number of words, trailing wildcard) -> "word1 word2"
# Scopus rejects wildcards inside multi-word quoted phrases entirely;
# we sacrifice the wildcard to keep the phrase match.
_RE_B = re.compile(r'"([A-Za-z][A-Za-z0-9\-]*(?:\s+[A-Za-z][A-Za-z0-9\-]*)+)\*"')

# Rule C: {exact-phrase*} -> {exact-phrase}  (Aurora curly-brace syntax)
_RE_C = re.compile(r'\{([^}]+)\*\}')

# Rule D: *word (leading unquoted wildcard, not preceded by word char) -> word
# Scopus rejects leading wildcards for performance reasons.
_RE_D = re.compile(r'(?<!\w)\*([A-Za-z][A-Za-z0-9]*)')

# B+ cleanup: infix wildcards in genuine quoted phrases,
#   e.g. "government* expenditure" -> "government expenditure"
# RESTRICTIVE char class: only word chars, hyphens, apostrophes, spaces --
# prevents matching across Scopus operators like W/3, (, ), etc.
_WORD = r"[A-Za-z][A-Za-z0-9\-\']*"
_WORDS_BEFORE = r"(?:" + _WORD + r"(?:\s+" + _WORD + r")*)"
_WORDS_AFTER  = r"(?:[A-Za-z0-9\-\' ]*)"
_RE_BPLUS = re.compile(
    r'"'
    + r"(" + _WORDS_BEFORE + r")"   # group 1: phrase words before the wildcard
    + r"\*"
    + r"(" + _WORDS_AFTER  + r")"   # group 2: optional continuation after wildcard
    + r'"'
)

# Final normalisation: collapse multiple spaces to one
_RE_SPACES = re.compile(r' {2,}')


# ── Public API ────────────────────────────────────────────────────────────────

def clean_for_scopus(query: str) -> Tuple[str, List[Dict]]:
    """
    Clean a composed Scopus query string.

    Parameters
    ----------
    query : str  Full composed query (may be several hundred KB).

    Returns
    -------
    cleaned : str
        Transformed query, safe for the current Scopus Advanced Search.
    log : list[dict]
        Audit log of every unique transformation made::

            [{'rule': 'A', 'original': '"child*"',
              'replacement': 'child*', 'count': 3}, ...]

        Sorted by rule then original string.
    """
    counts: Dict[Tuple[str, str, str], int] = {}

    def _apply(rule_id: str, pattern: re.Pattern, repl, text: str) -> str:
        def _sub(m: re.Match) -> str:
            orig = m.group(0)
            rep = repl(m) if callable(repl) else m.expand(repl)
            if orig != rep:
                key = (rule_id, orig, rep)
                counts[key] = counts.get(key, 0) + 1
            return rep
        return pattern.sub(_sub, text)

    result = query

    # Apply rules in prescribed order
    result = _apply("A", _RE_A, r"\1",   result)
    result = _apply("B", _RE_B, r'"\1"', result)
    result = _apply("C", _RE_C, r'{\1}', result)
    result = _apply("D", _RE_D, r"\1",   result)

    # B+ cleanup: strip infix wildcards from remaining genuine quoted phrases.
    # Counted under rule "B" since it is the same semantic operation.
    # Loop until stable in case a phrase has multiple infix wildcards.
    prev = None
    while prev != result:
        prev = result
        result = _apply(
            "B",
            _RE_BPLUS,
            lambda m: f'"{m.group(1)}{m.group(2)}"',
            result,
        )

    result = _RE_SPACES.sub(" ", result)

    log = [
        {"rule": rule, "original": orig, "replacement": rep, "count": cnt}
        for (rule, orig, rep), cnt in sorted(
            counts.items(), key=lambda x: (x[0][0], x[0][1])
        )
    ]
    return result, log


def count_by_rule(log: List[Dict]) -> Dict[str, int]:
    """Return total transformation count per rule letter."""
    totals: Dict[str, int] = {}
    for entry in log:
        r = entry["rule"]
        totals[r] = totals.get(r, 0) + entry["count"]
    return totals
