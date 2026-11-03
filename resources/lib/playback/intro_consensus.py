"""Combine eligible opening timings for the file currently playing."""
from resources.lib.playback import timing_rules as rules

TOLERANCE = 3


def community_candidates(rows, duration, mode):
    from resources.lib.playback.timing_match import assess

    by_provider = {}
    for row in rows:
        if isinstance(row, dict):
            by_provider.setdefault(rules.group(row)[0], []).append(row)
    return [result for group in by_provider.values()
            if (result := assess(group, duration, mode=mode)['intro']) is not None]


def choose(duration, chapter=None, confirmed=None, community=(), audio=None):
    if confirmed and rules.interval(confirmed, duration):
        # Preserve the existing labelled-chapter preference for this file.
        if chapter:
            return dict(range=chapter, provider='File chapters', unverified=False, online=False)
        return dict(confirmed, unverified=False, online=False)

    evidence = []
    if chapter:
        evidence.append((chapter, 'File chapters', 3, False))
    if audio:
        bounds = rules.interval(audio, duration)
        if bounds:
            evidence.append((bounds, 'Audio match', 2, False))

    seen_ranges = set()
    for row in sorted(community, key=lambda value: bool(value.get('unverified'))):
        bounds = rules.interval(row, duration)
        if bounds and bounds not in seen_ranges:
            seen_ranges.add(bounds)
            evidence.append((bounds, row['provider'], 1 if row.get('unverified') else 2, True))
    if not evidence:
        return None

    # A cluster must fit within the tolerance at both ends, even if a chain
    # of intermediate values could connect two different cuts.
    groups = []
    for start, _ in (entry[0] for entry in evidence):
        for _, end in (entry[0] for entry in evidence):
            group = [entry for entry in evidence
                     if start <= entry[0][0] <= start + TOLERANCE
                     and end <= entry[0][1] <= end + TOLERANCE]
            if group and group not in groups:
                groups.append(group)
    if chapter:
        groups = [group for group in groups if any(entry[2] == 3 for entry in group)]
    score = lambda group: (sum(entry[2] for entry in group), len(group))
    groups.sort(key=score, reverse=True)
    best = groups[0]
    if len(groups) > 1 and score(best) == score(groups[1]):
        if chapter:
            return dict(range=chapter, provider='File chapters', unverified=False, online=False)
        return None

    total = sum(entry[2] for entry in best)
    bounds = tuple(round(sum(entry[0][index] * entry[2] for entry in best) / total, 3)
                   for index in (0, 1))
    if not rules.interval(dict(kind='intro', start=bounds[0], end=bounds[1]), duration):
        return None
    return dict(range=bounds, provider=best[0][1] if len(best) == 1 else 'Timing agreement',
                unverified=not chapter and (len(best) == 1 and
                    (best[0][2] == 1 or not best[0][3]) or all(entry[2] == 1 for entry in best)),
                online=any(entry[3] for entry in best))
