"""
scopus_query_clean.py
Sanitise Aurora SDG composed queries for the current Scopus parser.

Scopus (2024+) rejects wildcards (*) inside quoted strings, which
causes the entire TITLE-ABS-KEY clause to return zero results.
This module provides clean_for_scopus() which applies five rules in
sequence to remove or unquote problematic wildcard patterns while
preserving all Boolean operators, proximity operators, country names,
year/doctype filters, and unquoted trailing wildcards.

Rules applied in order:
  A  - "word*"       -> word*          (unquote single-token wildcard)
  B  - "w1 w2*"     -> "w1 w2"       (strip trailing wildcard from phrase)
  C  - {phrase*}     -> {phrase}       (strip wildcard from exact-match braces)
  D  - *word         -> word           (remove unsupported leading wildcard)
  B+ - "w1* w2"     -> "w1 w2"       (cleanup: infix wildcard in quoted phrase)
  E  - "w1* w2*"    -> (w1* W/1 w2*) (multi-wildcard phrase -> proximity)
  F  - prefix-suffix* -> prefixsuffix* (unhyphenate wildcard compound)
  G  - (wc*) W/n (y) -> (wc*) AND (y) (proximity+wildcard -> AND)
  G2a- (wc*) W/n    -> (wc*) AND      (wildcard group before W/n, complex right side)
  G2b- W/n (wc*)    -> AND (wc*)      (W/n before wildcard group, complex left side)
  G3a- (deep*) W/n  -> (deep*) AND    (deep nested left group containing wildcard)
  G3b- W/n (deep*)  -> AND (deep*)    (W/n before deep nested right group with wildcard)

Root cause of B+ restriction:
  The naive r'"([^"]*)\\*([^"]*)"' pattern is intentionally NOT used for B+.
  Because [^"]* matches the asterisk itself, that pattern can span from the
  closing " of one quoted token across unquoted wildcards (produced by Rule A)
  to the opening " of the next quoted token, thereby erasing wildcards that
  were legitimately converted by Rule A.  The restrictive _RE_BPLUS below
  only matches genuine multi-word quoted phrases by requiring all characters
  inside the quotes to be word chars, spaces, hyphens, or apostrophes --
  never Scopus operator chars like W, /, (, ), etc.

Rule E motivation:
  After B and B+ run, quoted phrases with multiple wildcards (e.g.
  "develop* countr*", "myocard* infarct*") remain unhandled because B+
  cannot consume WORDS_AFTER when it contains a second asterisk.  Rule E
  converts these to W/1 proximity expressions so both wildcards stay valid
  and the adjacency constraint is preserved.

Rule G motivation:
  Scopus rejects W/n when either adjacent operand group contains an
  unquoted wildcard (same error class as the documented unsupported
  example "{nitrous oxide} W/2 emission*").  Rule G replaces the W/n
  with AND, preserving the Boolean relationship while sacrificing
  proximity precision -- acceptable for continental-scale thematic mapping.

  The pattern uses TWO alternating sub-patterns so the engine only
  advances past a W/n match when at least one side HAS a wildcard.
  If neither side has a wildcard the engine fails at that position and
  continues scanning, so downstream wildcard W/n pairs in the same
  (or chained) expression are still found in the same pass.
  A loop repeats until stable because a chain (a*) W/n (b) W/n (c*)
  may need two passes: the first replaces (a*) W/n (b), exposing
  (b) W/n (c*) for the second pass.

Rules G2a / G2b motivation:
  Rule G requires BOTH operands to be simple parenthesised groups with
  no nested parens ([^()]*).  Eleven SDGs contain W/n where one side
  is either a complex nested group (e.g. (("neonatal" OR ...) W/3 (...)))
  or a bare quoted term.  G2a and G2b each check only ONE side:
    G2a fires when the LEFT operand is a wildcard paren group _WC_G,
        replacing "(wc*) W/n" with "(wc*) AND" regardless of right side.
    G2b fires when the RIGHT operand is a wildcard paren group _WC_G,
        replacing "W/n (wc*)" with "AND (wc*)" regardless of left side.
  Both are run in a joint loop until stable; they are logged under rule G.

Rules G3a / G3b motivation:
  G2b can introduce a new invalid pattern: when it converts an INNER W/n
  to AND (e.g. "maternal" W/3 ("mortality" OR death*) -> "maternal" AND ...),
  the OUTER W/n's operand now contains AND, which Scopus rejects as a
  proximity operand ("Unexpected input at position N").  G3a and G3b use
  a deeper _G3 pattern (handles up to 3 levels of nested parens) together
  with a programmatic wildcard check so they fire on any wildcard-containing
  group regardless of nesting depth.  They run after G2a/G2b in a joint
  loop until stable; logged under rule G.
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

# Rule E: remaining quoted phrases with multiple wildcards,
#   e.g. "develop* countr*" -> (develop* W/1 countr*)
# Applied after B+ so that single-infix-wildcard phrases are already cleaned.
# Character class excludes Scopus operators (W, /, (, ), etc.) -- same
# restriction as _RE_BPLUS but allows * in the interior.
_RE_E = re.compile(r'"([A-Za-z][A-Za-z0-9\- ]*\*[A-Za-z0-9\- *]*)"')

# Rule F: unquoted hyphenated wildcard compound -> concatenated wildcard
#   e.g. socio-economic* -> socioeconomic*, micro-financ* -> microfinanc*
# Scopus treats hyphens as spaces, so prefix-suffix* becomes two tokens
# "prefix" and "suffix*"; but the hyphenated form itself triggers the
# unsupported-wildcard parser error (same class as the (fire-*) example).
# Lookbehind (?<![A-Za-z0-9"]) prevents matching inside already-quoted strings
# or inside a longer word that happens to contain a hyphen mid-token.
_RE_F = re.compile(r'(?<![A-Za-z0-9"])([A-Za-z][A-Za-z0-9]+)-([A-Za-z][A-Za-z0-9]*\*)')

# Rule G: W/n proximity operator adjacent to a wildcard-bearing group -> AND
# _WC_G matches a parenthesised group that CONTAINS *  (wildcard group)
# _NW_G matches a parenthesised group that does NOT contain * (no-wildcard group)
#   [^()*] excludes (, ), and * from the interior character class.
# Two-alternative pattern so the regex engine FAILS (rather than consuming
# and returning unchanged) when neither side has a wildcard:
#   Alt 1 – left group has *; right group can be anything.
#   Alt 2 – left group has NO *; right group has *.
# This failure-on-no-wildcard property means (a) W/n (b) W/n (c*) is
# handled correctly in one pass: the engine skips (a) W/n (b) without
# advancing past (b), then matches (b) W/n (c*) immediately after.
_WC_G = r'\([^()]*\*[^()]*\)'    # paren group containing  *
_NW_G = r'\([^()*]*\)'            # paren group without     *
_RE_G = re.compile(
    r'(' + _WC_G + r')\s*(W/\d+)\s*(' + _WC_G + r'|' + _NW_G + r')'  # Alt 1
    + r'|'
    + r'(' + _NW_G + r')\s*(W/\d+)\s*(' + _WC_G + r')'                # Alt 2
)

# G2a: wildcard paren group immediately BEFORE W/n; right side unconstrained.
# Fires after the main Rule G loop to catch cases where the right operand
# is a complex nested group that _RE_G's [^()]* could not consume.
_RE_G2A = re.compile(r'(' + _WC_G + r')\s*(W/\d+)')

# G2b: W/n immediately BEFORE a wildcard paren group; left side unconstrained.
_RE_G2B = re.compile(r'(W/\d+)\s*(' + _WC_G + r')')

# G3 character-scanner helpers: balanced-paren search, O(n), no regex.
# Used instead of a regex-based _G3 pattern because Python's `re` module
# lacks possessive quantifiers; any nested (?:A|B)* on long strings risks
# catastrophic backtracking that cannot be tamed without atomic groups.

def _g3_find_close(s: str, pos: int) -> int:
    """Return index of ')' matching '(' at pos, or -1 if unmatched."""
    depth = 0
    for i in range(pos, len(s)):
        if s[i] == '(':   depth += 1
        elif s[i] == ')':
            depth -= 1
            if depth == 0: return i
    return -1

def _g3_find_open(s: str, pos: int) -> int:
    """Return index of '(' matching ')' at pos, or -1 if unmatched."""
    depth = 0
    for i in range(pos, -1, -1):
        if s[i] == ')':   depth += 1
        elif s[i] == '(':
            depth -= 1
            if depth == 0: return i
    return -1

_RE_WN = re.compile(r'W/\d+')   # locates W/n tokens for the G3 scanner

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

    # B+ cleanup: strip single infix wildcard from remaining genuine quoted phrases.
    # Counted under rule "B" since it is the same semantic operation.
    # Loop until stable in case a phrase has multiple infix wildcards that can
    # be handled one at a time (only possible when WORDS_AFTER has no trailing *).
    prev = None
    while prev != result:
        prev = result
        result = _apply(
            "B",
            _RE_BPLUS,
            lambda m: f'"{m.group(1)}{m.group(2)}"',
            result,
        )

    # Rule E: any still-quoted phrase containing * (multi-wildcard patterns
    # that B+ cannot reach) -> W/1 proximity expression.
    def _e_repl(m: re.Match) -> str:
        tokens = m.group(1).strip().split()
        return "(" + " W/1 ".join(tokens) + ")"

    result = _apply("E", _RE_E, _e_repl, result)

    # Rule F: unhyphenate unquoted wildcard compounds.
    result = _apply("F", _RE_F, lambda m: m.group(1) + m.group(2), result)

    # Rule G: W/n adjacent to wildcard group -> AND.
    # Alt 1 matched when group 1 is set; Alt 2 when group 4 is set.
    def _g_repl(m: re.Match) -> str:
        if m.group(1) is not None:          # Alt 1: left has wildcard
            return f"{m.group(1)} AND {m.group(3)}"
        return f"{m.group(4)} AND {m.group(6)}"  # Alt 2: only right has wildcard

    prev = None
    while prev != result:
        prev = result
        result = _apply("G", _RE_G, _g_repl, result)

    # G2a / G2b: catch remaining W/n+wildcard cases where one operand is
    # a complex nested group that _RE_G could not consume.
    # Both are counted under rule G and looped until stable.
    prev = None
    while prev != result:
        prev = result
        result = _apply("G", _RE_G2A, lambda m: f"{m.group(1)} AND", result)
        result = _apply("G", _RE_G2B, lambda m: f"AND {m.group(2)}", result)

    # G3 scanner: G2b can create a new invalid pattern — when it converts an
    # inner W/n to AND the OUTER W/n's operand now contains AND, which Scopus
    # rejects as a proximity operand ("Unexpected input at position N").
    # A regex-based fix would need nested (?:A|B)* patterns that cause
    # catastrophic backtracking in Python's re module (no possessive quantifiers).
    # The character scanner avoids that entirely: O(n) per W/n, guaranteed.
    # Logged under rule G, loop until stable.
    g3_changed = True
    while g3_changed:
        g3_changed = False
        idx = 0
        while idx < len(result):
            m = _RE_WN.match(result, idx)
            if m is None:
                idx += 1
                continue
            ws, we, wn = m.start(), m.end(), m.group(0)
            replaced = False

            # RIGHT: paren group immediately after W/n (skip spaces)
            j = we
            while j < len(result) and result[j] == ' ':
                j += 1
            if j < len(result) and result[j] == '(':
                rend = _g3_find_close(result, j)
                if rend != -1 and '*' in result[j:rend + 1]:
                    right = result[j:rend + 1]
                    orig  = result[ws:rend + 1]
                    rep   = 'AND ' + right
                    key   = ("G", orig, rep)
                    counts[key] = counts.get(key, 0) + 1
                    result = result[:ws] + rep + result[rend + 1:]
                    g3_changed = True
                    idx = ws
                    replaced = True

            # LEFT: paren group immediately before W/n (skip spaces)
            if not replaced:
                k = ws - 1
                while k >= 0 and result[k] == ' ':
                    k -= 1
                if k >= 0 and result[k] == ')':
                    lstart = _g3_find_open(result, k)
                    if lstart != -1 and '*' in result[lstart:k + 1]:
                        left  = result[lstart:k + 1]
                        orig  = result[lstart:we]
                        rep   = left + ' AND '
                        key   = ("G", orig, rep)
                        counts[key] = counts.get(key, 0) + 1
                        result = result[:lstart] + rep + result[we:]
                        g3_changed = True
                        idx = lstart
                        replaced = True

            if not replaced:
                idx = we

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
