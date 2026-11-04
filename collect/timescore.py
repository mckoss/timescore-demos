"""TimeScore: a time-weighted score, stored as a single number per item.

Every event (a like, a click, a share) is worth its full value when it
happens, half as much one half-life later, a quarter after two, and so on.
An item's score at any moment is the sum of its events' faded values.

Rather than fading old events as time passes, each event is boosted by
2 ** (time / half_life) when it is added, and the item stores the (natural)
log of the sum. Every item's score fades at the same rate, so the stored numbers
never change between events, and sorting by them ranks items by their
current score. (The log keeps the number small: the sum itself would pass
the largest float after 1024 half-lives.)

Times can be in any unit (hours, seconds, days) measured from any fixed
epoch, as long as the half-life is in the same unit.

Because the stored score is the log of a plain sum, two scores for the same
item (say, from two replicas of a database, each counting different events)
merge with combine().

TimeScore is in the public domain: free for anyone to use. If you use it,
a credit is appreciated: "TimeScore algorithm courtesy Mike Koss"
(https://mckoss.com).
"""

import math

EMPTY = -math.inf
"""The stored score of an item with no events yet."""

LN2 = math.log(2)


def event_score(value: float, time: float, half_life: float) -> float:
    """The stored score of a single event: log(value * 2 ** (time / half_life)).

    value:     the event's value, greater than 0 (1 for a like)
    time:      when the event happened
    half_life: the time it takes an event's value to halve
    """
    if not value > 0:
        raise ValueError(f"TimeScore values must be greater than 0, not {value}")
    return math.log(value) + time * LN2 / half_life


def combine(a: float, b: float) -> float:
    """Two stored scores merged into one, as if one item had had both scores'
    events: log(e**a + e**b), computed without leaving the log domain.

    a: a stored score (EMPTY for none)
    b: another stored score with the same half-life
    """
    high = max(a, b)
    low = min(a, b)
    if low == -math.inf:
        return high
    return high + math.log1p(math.exp(low - high))


def add_event(log_score: float, value: float, time: float, half_life: float) -> float:
    """Add an event to an item's stored score, and return the new stored score.

    log_score: the item's stored score (EMPTY if it has none)
    value:     the event's value, greater than 0 (1 for a like)
    time:      when the event happened
    half_life: the time it takes an event's value to halve
    """
    return combine(log_score, event_score(value, time, half_life))


def score_at(log_score: float, time: float, half_life: float) -> float:
    """An item's score at a given time, at or after its latest event: the sum
    of its events' values, each halved for every half-life since it happened.

    log_score: the item's stored score
    time:      the time to score it at
    half_life: the same half-life its events were added with
    """
    return math.exp(log_score - time * LN2 / half_life)
