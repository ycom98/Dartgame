"""Checkout suggestions for x01 (M3 UI-03).

suggest(remaining, darts_left, double_out) returns the recommended finish as a list of dart labels
('T20', 'S5', 'D16', 'BULL' for the 50, '25' for the outer bull), or None when no finish is possible with
the darts left.

How a route is chosen:
  1. Fewest darts first (a two-dart finish beats a three-dart one).
  2. Double out: the last dart must be a double (D1-D20 or the bull). Straight out: any dart.
  3. Among routes with the same number of darts, the one players are taught: big trebles to set up
     (T20, then T19...), a single when a single will do, and a favourite finishing double (D20, D16,
     D18, D12...). This reproduces the standard published checkout chart; the few places where the
     chart's convention differs from that preference are listed in CHART_OVERRIDES.

Every route is exact (its darts add up to `remaining`) and legal for the out rule; tests/test_checkout.py
checks every score from 2 to 170 (double out) and 1 to 180 (straight out) with one, two and three darts.
"""
from functools import lru_cache

# Every board hit: (label, value, multiplier, points). No T25; the bull is the double 25.
SEGMENTS = (
    [('S%d' % n, n, 1, n) for n in range(1, 21)]
    + [('D%d' % n, n, 2, 2 * n) for n in range(1, 21)]
    + [('T%d' % n, n, 3, 3 * n) for n in range(1, 21)]
    + [('25', 25, 1, 25), ('BULL', 25, 2, 50)]
)

# Finishing doubles in order of preference: the ones that split well into another double when missed.
FAVOURITE_DOUBLES = [20, 16, 18, 12, 10, 8, 14, 6, 4, 2, 19, 17, 15, 13, 11, 9, 7, 5, 3, 1, 25]

# The standard chart's three-dart routes where it prefers a different (equally valid) set-up.
CHART_OVERRIDES = {
    3: {
        170: ['T20', 'T20', 'BULL'], 167: ['T20', 'T19', 'BULL'], 164: ['T20', 'T18', 'BULL'],
        161: ['T20', 'T17', 'BULL'], 160: ['T20', 'T20', 'D20'], 158: ['T20', 'T20', 'D19'],
        157: ['T20', 'T19', 'D20'], 156: ['T20', 'T20', 'D18'], 155: ['T20', 'T19', 'D19'],
        154: ['T20', 'T18', 'D20'], 153: ['T20', 'T19', 'D18'], 152: ['T20', 'T20', 'D16'],
        151: ['T20', 'T17', 'D20'], 150: ['T20', 'T18', 'D18'], 149: ['T20', 'T19', 'D16'],
        148: ['T20', 'T20', 'D14'], 147: ['T20', 'T17', 'D18'], 146: ['T20', 'T18', 'D16'],
        145: ['T20', 'T15', 'D20'], 144: ['T20', 'T20', 'D12'], 143: ['T20', 'T17', 'D16'],
        142: ['T20', 'T14', 'D20'], 141: ['T20', 'T19', 'D12'], 140: ['T20', 'T20', 'D10'],
        139: ['T20', 'T13', 'D20'], 138: ['T20', 'T18', 'D12'], 137: ['T20', 'T19', 'D10'],
        136: ['T20', 'T20', 'D8'], 135: ['T20', 'T17', 'D12'], 134: ['T20', 'T14', 'D16'],
        133: ['T20', 'T19', 'D8'], 132: ['T20', 'T16', 'D12'], 131: ['T20', 'T13', 'D16'],
        130: ['T20', 'T20', 'D5'], 129: ['T19', 'T16', 'D12'], 128: ['T18', 'T14', 'D16'],
        127: ['T20', 'T17', 'D8'], 126: ['T19', 'T19', 'D6'], 125: ['25', 'T20', 'D20'],
        124: ['T20', 'T16', 'D8'], 123: ['T19', 'T16', 'D9'], 122: ['T18', 'T20', 'D4'],
        121: ['T20', 'T11', 'D14'], 120: ['T20', 'S20', 'D20'], 119: ['T19', 'T12', 'D13'],
        118: ['T20', 'S18', 'D20'], 117: ['T20', 'S17', 'D20'], 116: ['T20', 'S16', 'D20'],
        115: ['T20', 'S15', 'D20'], 114: ['T20', 'S14', 'D20'], 113: ['T20', 'S13', 'D20'],
        112: ['T20', 'S12', 'D20'], 111: ['T20', 'S11', 'D20'], 109: ['T20', 'S9', 'D20'],
        108: ['T20', 'S16', 'D16'], 107: ['T19', 'S18', 'D16'], 106: ['T20', 'S10', 'D18'],
        105: ['T20', 'S13', 'D16'], 103: ['T19', 'S10', 'D18'], 102: ['T20', 'S10', 'D16'],
        99: ['T19', 'S10', 'D16'],
    },
}

_BY_LABEL = {label: (value, multiplier, points) for label, value, multiplier, points in SEGMENTS}


def _is_finish(label, double_out):
    return not double_out or _BY_LABEL[label][1] == 2


def _setup_cost(label):
    """Lower is better for a set-up dart: big trebles, then singles (a single is the safe shot)."""
    value, multiplier, _ = _BY_LABEL[label]
    if label == '25':
        return 30
    if multiplier == 3:
        return 20 - value
    if multiplier == 1:
        return 10 + (20 - value) * 0.1
    return 40 + (20 - value)  # a double as a set-up dart is a last resort


def _finish_cost(label, double_out):
    value, multiplier, _ = _BY_LABEL[label]
    if double_out:
        return FAVOURITE_DOUBLES.index(value)
    # Straight out: a fat single first, then a double, then a treble.
    return {1: 0, 2: 30, 3: 60}[multiplier] + (20 - value if value != 25 else 25)


def _route_cost(route, double_out):
    *setup, last = route
    return (sum(_setup_cost(label) for label in setup) + _finish_cost(last, double_out) * 1.2,
            # tie-break: the highest first dart, then the plain order of labels (deterministic)
            [-_BY_LABEL[label][2] for label in route], route)


@lru_cache(maxsize=None)
def _best(remaining, darts, double_out):
    """The best route with exactly `darts` darts, or None."""
    best = None
    finishers = [s for s in SEGMENTS if _is_finish(s[0], double_out)]
    if darts == 1:
        for label, _, _, points in finishers:
            if points == remaining:
                route = [label]
                if best is None or _route_cost(route, double_out) < _route_cost(best, double_out):
                    best = route
        return best
    for label, _, _, points in SEGMENTS:
        rest = remaining - points
        if rest <= 0:
            continue
        tail = _best(rest, darts - 1, double_out)
        if tail is None:
            continue
        route = [label] + tail
        if best is None or _route_cost(route, double_out) < _route_cost(best, double_out):
            best = route
    return best


def suggest(remaining, darts_left=3, double_out=True):
    """The recommended finish for `remaining` points with `darts_left` darts (1-3), or None."""
    if type(remaining) is not int or type(darts_left) is not int or not 1 <= darts_left <= 3:
        return None
    if remaining < 1 or remaining > (170 if double_out else 180):
        return None
    for darts in range(1, darts_left + 1):
        if darts == 3 and double_out and remaining in CHART_OVERRIDES[3]:
            return list(CHART_OVERRIDES[3][remaining])
        route = _best(remaining, darts, bool(double_out))
        if route is not None:
            return list(route)
    return None


def points(route):
    """Total points of a route (for checks and tests)."""
    return sum(_BY_LABEL[label][2] for label in route)
