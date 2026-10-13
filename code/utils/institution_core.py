"""Institutional-core representation and conservative fuzzy acceptance gates for ROR matching.

Pure functions (no I/O). Used by code/02_affiliation_standardisation.py and tests. Country names come from the shared country
normaliser alias table (generic; never from the matched ROR record).

Gates applied to a fuzzy WINNER (all must pass; otherwise the segment abstains):
  A  substantive overlap   every substantive candidate token occurs in the segment (token similarity
                           >= 80 for tokens of >= 5 characters; exact otherwise)
  B  coverage              in that component the candidate explains > 50% of the distinctive tokens
                           (a short/generic name cannot win against a longer specific organisation)
  C  co-location           one comma-component (country-only components excluded) contains all
                           substantive tokens and, if the candidate names an institution type, a token
                           of the same type family
  D  numerals              Roman/Arabic numerals attached to a candidate token must agree with the segment
  E  generic-only          a candidate without distinctive (non-generic) tokens is accepted only when a
                           co-located window is fully explained by it (no more specific organisation named)
Coverage (B) ignores a leading unit description ending in a sub-unit word ('Pomology Department Faculty of
Agriculture Mansoura University') and, in B and E, a campus qualifier ('<name> Enugu Campus'); type words
are matched in plural too; spacing variants of candidate words are accepted ('Al Nas' ~ 'ALNas').
Windows are runs of 1-3 adjacent comma-components (country-only components excluded); token matching
allows concatenation of adjacent tokens ('El Oued' ~ 'Eloued') and similarity >= 80 for tokens >= 5 chars.
Gate F (candidate margin) is the pre-existing score gap >= 5 / perfect-tie abstention.
"""
from __future__ import annotations

import re
import unicodedata

from rapidfuzz import fuzz

TYPE_FAMILIES = {
    "university": {"university", "universite", "universidad", "universidade", "universita", "universitat", "universiteit", "univ"},
    "institute": {"institute", "institut", "instituto", "istituto", "inst"},
    "hospital": {"hospital", "hopital", "hospitalier", "hospitaliere", "hospitalo"},
    "college": {"college"},
    "school": {"school", "ecole", "escola", "escuela"},
    "centre": {"centre", "center", "centro", "ctr"},
    "ministry": {"ministry", "ministere", "ministerio"},
    "council": {"council", "conseil"},
    "agency": {"agency", "agence"},
    "foundation": {"foundation", "fondation", "fundacao", "fundacion"},
    "laboratory": {"laboratory", "laboratoire", "laboratorio", "lab"},
    "academy": {"academy", "academie"},
    "polytechnic": {"polytechnic", "polytechnique", "politecnico"},
    "clinic": {"clinic", "clinique"},
    "society": {"society", "societe"},
    "organisation": {"organisation", "organization", "organisme"},
    "authority": {"authority", "autorite"},
    "board": {"board"},
    "office": {"office"},
    "museum": {"museum", "musee"},
}
_PLURALS = {"universities": "university", "institutes": "institute", "hospitals": "hospital", "colleges": "college",
            "schools": "school", "centres": "centre", "centers": "centre", "laboratories": "laboratory", "clinics": "clinic",
            "academies": "academy", "councils": "council", "agencies": "agency", "museums": "museum"}
TYPE_TOKENS = {t: fam for fam, toks in TYPE_FAMILIES.items() for t in toks}
TYPE_TOKENS.update({pl: TYPE_TOKENS[sg] for pl, sg in _PLURALS.items()})   # plural type words
# sub-unit words: in 'Pomology Department Faculty of Agriculture Mansoura University' the words up to the last
# sub-unit word before the institution name describe the unit, not a competing organisation (gate B only)
SUBUNIT = {"department", "departement", "dept", "faculty", "faculte", "facultad", "laboratory", "laboratoire", "lab",
           "division", "unit", "unite", "section", "programme", "program"}
STOP = {"the", "of", "and", "for", "in", "at", "on", "de", "des", "du", "la", "le", "les", "l", "d", "et", "en", "da", "do",
        "dos", "das", "e", "y", "del", "a", "an", "&", "au", "aux", "el", "al"}
# generic institution words: never sufficient evidence on their own
WEAK = {"national", "federal", "state", "regional", "central", "general", "international", "higher", "advanced", "applied",
        "research", "studies", "study", "sciences", "science", "scientific", "technology", "technologies", "technological",
        "technical", "engineering", "medical", "medicine", "health", "public", "agricultural", "agriculture", "agronomic",
        "environmental", "environment", "development", "management", "education", "educational", "teaching", "training",
        "nursing", "veterinary", "economic", "economics", "social", "nutrition", "water", "energy", "energies", "marine",
        "royal", "open", "new", "free", "catholic", "islamic", "christian", "american", "african", "africa", "arab", "west",
        "east", "north", "south", "southern", "northern", "eastern", "western", "upper", "lower", "great", "university",
        "institute", "faculty", "department", "division", "unit", "programme", "program", "project", "services", "service",
        "affairs", "resources", "resource", "industrial", "industry", "trade", "business", "finance", "law", "arts",
        "humanities", "pharmacy", "dentistry", "biology", "chemistry", "physics", "mathematics", "computer", "information",
        "communication", "communications", "statistics", "planning", "policy", "population", "community", "family",
        "children", "women", "youth", "rural", "urban", "city", "municipal", "county", "provincial", "district", "local",
        "teaching", "referral", "specialized", "specialised", "comprehensive", "memorial", "military", "police", "defence",
        "defense", "polytechnic", "metropolitan", "superieure", "superieur", "nationale", "national", "recherche", "sante",
        "sciences", "technologie", "techniques", "technique", "agronomique", "ingenieurs", "ingenierie", "etudes", "formation",
        "superior", "sup", "hautes", "ecole", "faculte", "nacional", "estudos", "pesquisa", "saude", "ciencias", "tecnologia",
        "group", "groupe", "network", "consortium", "partnership", "alliance", "association", "trust", "fund", "initiative"}
WEAK |= set(TYPE_TOKENS)
ROMAN = {"i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x", "xi", "xii", "xiii", "xiv", "xv"}


def fold(s: str) -> str:
    s = str(s).replace("’", "'").replace("‘", "'")
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    return s.casefold()


def tokens(s: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", fold(s)) if t]


def is_numeral(t: str) -> bool:
    return t in ROMAN or t.isdigit()


# ── deterministic exact-key normalisation ───────────────────────────
_ARTICLE_PHRASES = [" of a ", " de la ", " de las ", " du ", " des ", " der ", " van de ", " van den "]


def exact_key(s: str) -> str:
    """Exact-lookup key, applied identically to ROR names and affiliation text.

    Lowercase, punctuation->space, article phrases incl. ' of the ' removed; accent-folded; the standalone article 'the' is optional (removed everywhere,
    'of' is kept, so 'University of the Witwatersrand' == 'University of Witwatersrand');
    'center' == 'centre'; intra-word hyphens -> space."""
    s = fold(s)
    s = re.sub(r"[^\w\s-]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    padded = " " + s + " "
    for art in _ARTICLE_PHRASES:
        padded = padded.replace(art, " ")
    padded = padded.replace("-", " ")          # intra-word and stray hyphens ("KwaZulu- Natal")
    toks =[("centre" if t == "center" else t) for t in padded.split() if t != "the"]
    return " ".join(toks)


class CoreGates:
    """Institutional core + gates A-E. Country names are generic (alias table), never ROR-record specific."""

    def __init__(self, country_aliases):
        phrases = {tuple(tokens(a)) for a in country_aliases if tokens(a)}
        self.country_phrases = sorted(phrases, key=len, reverse=True)
        self.country_keys = {" ".join(p) for p in phrases}
        self.country_tokens = {t for p in phrases for t in p}

    def is_country_component(self, comp: str) -> bool:
        return " ".join(tokens(comp)) in self.country_keys

    def scoring_text(self, segment: str) -> str:
        """Affiliation text used for fuzzy SCORING: comma-components that are only a country name are
        removed, so a trailing country field cannot drive similarity."""
        comps = [c for c in segment.split(",") if c.strip() and not self.is_country_component(c)]
        return ", ".join(comps) if comps else segment

    def candidate_profile(self, name: str) -> dict:
        ct = tokens(name)
        subst = [t for t in ct if t not in STOP and not is_numeral(t) and t not in TYPE_TOKENS]
        distinct = [t for t in subst if t not in WEAK]
        fams = {TYPE_TOKENS[t] for t in ct if t in TYPE_TOKENS}
        nums = [(ct[i - 1] if i else None, t) for i, t in enumerate(ct) if is_numeral(t)]
        return {"tokens": ct, "substantive": subst, "distinctive": distinct, "types": fams, "numerals": nums,
                "noncountry_distinctive": [t for t in distinct if t not in self.country_tokens]}

    @staticmethod
    def _expand(toks: list[str]) -> list[str]:
        """Tokens plus concatenations of adjacent pairs ('el'+'oued' -> 'eloued')."""
        return toks + [toks[i] + toks[i + 1] for i in range(len(toks) - 1)]

    @classmethod
    def _cand_match(cls, ct: list[str], i: int, seg_toks) -> bool:
        """Candidate token ct[i] occurs in the segment, alone or as part of an exact concatenation with
        its neighbour in the candidate name (spacing variants: 'Al Nas' ~ 'ALNas')."""
        if cls._tok_match(ct[i], seg_toks):
            return True
        pool = cls._expand(list(seg_toks))
        return (i > 0 and ct[i - 1] + ct[i] in pool) or (i + 1 < len(ct) and ct[i] + ct[i + 1] in pool)

    @classmethod
    def _tok_match(cls, t: str, seg_toks) -> bool:
        pool = cls._expand(list(seg_toks))
        if t in pool:
            return True
        if len(t) >= 5:
            return any(len(u) >= 4 and fuzz.ratio(t, u) >= 80 for u in pool)
        return False

    def _windows(self, segment: str):
        """Contiguous runs of 1-3 comma-components (country-only components excluded), as
        (tokens, tokens_without_parentheticals)."""
        comps = [c for c in segment.split(",") if tokens(c) and not self.is_country_component(c)]
        out = []
        for i in range(len(comps)):
            for k in (1, 2, 3):
                if i + k <= len(comps):
                    txt = ",".join(comps[i:i + k])
                    out.append((tokens(txt), tokens(re.sub(r"\([^)]*\)", " ", txt))))
        return comps, out

    def gates(self, segment: str, name: str) -> tuple[bool, list[str]]:
        prof = self.candidate_profile(name)
        comps, wins = self._windows(segment)
        seg_toks = [t for c in comps for t in tokens(c)]
        subst = prof["substantive"]
        ct = prof["tokens"]
        sub_idx = [i for i, t in enumerate(ct) if t not in STOP and not is_numeral(t) and t not in TYPE_TOKENS]
        cand_pool = ct + self._expand(ct)
        failed = []

        def all_subst(toks):
            return bool(sub_idx) and all(self._cand_match(ct, i, toks) for i in sub_idx)

        # A substantive overlap (institution text; trailing country-only fields excluded)
        if not all_subst(seg_toks):
            failed.append("A_substantive_overlap")
        # C co-location: a window of 1-3 adjacent components holds all substantive tokens (+ type family)
        coloc = [w for w in wins if all_subst(w[0])
                 and (not prof["types"] or any(TYPE_TOKENS.get(t) in prof["types"] for t in w[0]))]
        if not coloc:
            failed.append("C_component_colocation")

        def explained(t):
            return t in cand_pool or self._tok_match(t, cand_pool)

        def drop_campus(toks):
            """'<name> <qualifier...> Campus': the words between the last candidate-explained word and
            'campus' (and 'campus' itself) name a campus OF the institution, not another organisation."""
            out = list(toks)
            while "campus" in out:
                j = out.index("campus")
                k = j - 1
                while k >= 0 and not explained(out[k]):
                    k -= 1
                out = out[:k + 1] + out[j + 1:]
            return out

        def drop_subunit_prefix(toks):
            """Ignore words up to the last sub-unit word (not part of the candidate name) that precedes the
            first candidate-explained substantive word in the component."""
            first = next((i for i, t in enumerate(toks) if t not in STOP and t not in WEAK and explained(t)), None)
            if first is None:
                return toks
            cut = max((i for i in range(first) if toks[i] in SUBUNIT and toks[i] not in ct), default=-1)
            return toks[cut + 1:]

        def unexplained(w):
            body = [t for t in drop_campus(w[1]) if t not in STOP and not is_numeral(t)]
            return [t for t in body if t not in cand_pool and not self._tok_match(t, cand_pool)]

        # B coverage: the candidate explains > 50% of the distinctive tokens of the institution-bearing
        #   component(s) - each component in the window carrying the candidate's type family (or the whole
        #   window for untyped candidates); a token may also be explained by its EXACT concatenation with
        #   a neighbour ('el'+'oued' = 'eloued'); share must exceed 50%
        def explained_share(toks):
            cd_idx = [i for i, t in enumerate(toks) if t not in STOP and t not in WEAK and not is_numeral(t)]
            if not cd_idx:
                return 1.0
            hit = 0
            for i in cd_idx:
                t = toks[i]
                joined = [t] + ([toks[i - 1] + t] if i else []) + ([t + toks[i + 1]] if i + 1 < len(toks) else [])
                if t in cand_pool or self._tok_match(t, cand_pool) or any(j in cand_pool for j in joined[1:]):
                    hit += 1
            return hit / len(cd_idx)

        def prep(c):
            return drop_subunit_prefix(drop_campus(c))

        def coverage_ok(w, txt_comps):
            if not prof["types"]:
                return explained_share(prep(w[1])) > 0.5
            typed = [c for c in txt_comps if any(TYPE_TOKENS.get(t) in prof["types"] for t in c)]
            return bool(typed) and all(explained_share(prep(c)) > 0.5 for c in typed)

        win_comps = {}
        for i in range(len(comps)):
            for k in (1, 2, 3):
                if i + k <= len(comps):
                    win_comps[tuple(tokens(",".join(comps[i:i + k])))] = [
                        tokens(re.sub(r"\([^)]*\)", " ", c)) for c in comps[i:i + k]]
        if coloc and not any(coverage_ok(w, win_comps[tuple(w[0])]) for w in coloc):
            failed.append("B_component_coverage")
        # D numerals attached to the same preceding token must agree (V vs VI, II vs III)
        cand_pairs = set(prof["numerals"])
        cand_prev = {p for p, _ in prof["numerals"]}
        for c in comps:
            ct = tokens(c)
            for i, t in enumerate(ct[:-1]):
                nxt = ct[i + 1]
                if t in cand_prev and is_numeral(nxt) and (t, nxt) not in cand_pairs:
                    failed.append("D_numeral_conflict")
                elif t in prof["tokens"] and t not in STOP and t not in cand_prev and nxt in ROMAN:
                    failed.append("D_numeral_conflict")
        # E generic-only candidates: accepted only if some co-located window is FULLY explained by the
        #   candidate (no unexplained word, parentheticals ignored) - i.e. no more specific organisation
        if not prof["distinctive"]:
            if not any(not [t for t in unexplained(w) if t not in WEAK or t not in prof["tokens"]] and
                       not [t for t in unexplained(w)] for w in coloc):
                failed.append("E_generic_only")
        failed = sorted(set(failed))
        return not failed, failed
