from __future__ import annotations

from dataclasses import dataclass

TIER_ORDER = ["aristocrat", "baron", "bourgeois", "commoner", "peasant", "beggar", "newcomer"]

_POSITIVE_BANDS = ["aristocrat", "baron", "bourgeois", "commoner"]
_NEGATIVE_BANDS = ["beggar", "peasant"]


@dataclass(frozen=True)
class TierInput:
    user_id: str
    name: str
    donated: int   # nano-AIU others burned from this user's gifts
    consumed: int  # nano-AIU this user drew from the pool


@dataclass(frozen=True)
class TierResult:
    user_id: str
    name: str
    net: int
    tier: str


def assign_tiers(entries: list[TierInput]) -> list[TierResult]:
    """Assign aristocracy tiers from real metered contribution.

    net = donated - consumed. net>=0 with activity -> top four bands by
    quartile (rank*4//count). net<0 -> bottom two bands by half
    (rank*2//count), most-negative first = beggar. Zero activity -> newcomer.
    Output: active entries sorted by net desc (ties by name asc), newcomers last.
    """
    newcomers = [e for e in entries if e.donated == 0 and e.consumed == 0]
    active = [e for e in entries if not (e.donated == 0 and e.consumed == 0)]

    positives = sorted(
        [e for e in active if e.donated - e.consumed >= 0],
        key=lambda e: (-(e.donated - e.consumed), e.name),
    )
    negatives = sorted(
        [e for e in active if e.donated - e.consumed < 0],
        key=lambda e: (e.donated - e.consumed, e.name),  # most negative first
    )

    results: list[TierResult] = []
    p = len(positives)
    for i, e in enumerate(positives):
        band = _POSITIVE_BANDS[i * 4 // p]
        results.append(TierResult(e.user_id, e.name, e.donated - e.consumed, band))

    neg_results: list[TierResult] = []
    n = len(negatives)
    for j, e in enumerate(negatives):
        band = _NEGATIVE_BANDS[j * 2 // n]
        neg_results.append(TierResult(e.user_id, e.name, e.donated - e.consumed, band))
    # negatives were most-negative-first for banding; output net desc
    neg_results.sort(key=lambda r: (-r.net, r.name))
    results.extend(neg_results)

    for e in sorted(newcomers, key=lambda e: e.name):
        results.append(TierResult(e.user_id, e.name, 0, "newcomer"))

    return results
