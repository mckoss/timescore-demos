// TimeScore: a time-weighted score, stored as a single number per item.
//
// Every event (a like, a click, a share) is worth its full value when it
// happens, half as much one half-life later, a quarter after two, and so on.
// An item's score at any moment is the sum of its events' faded values.
//
// Rather than fading old events as time passes, each event is boosted by
// 2^(time / halfLife) when it is added, and the item stores the (natural) log
// of the sum. Every item's score fades at the same rate, so the stored numbers
// never change between events, and sorting by them ranks items by their
// current score. (The log keeps the number small: the sum itself would pass
// the largest double after 1024 half-lives.)
//
// Times can be in any unit (hours, seconds, days) measured from any fixed
// epoch, as long as the half-life is in the same unit.
//
// Because the stored score is the log of a plain sum, two scores for the same
// item (say, from two replicas of a database, each counting different
// events) merge with combine().
//
// TimeScore is in the public domain: free for anyone to use. If you use it,
// a credit is appreciated: "TimeScore algorithm courtesy Mike Koss"
// (https://mckoss.com).

/** The stored score of an item with no events yet. */
export const EMPTY = -Infinity;

/**
 * The stored score of a single event: log(value * 2^(time / halfLife)).
 *
 * @param {number} value    the event's value, greater than 0 (1 for a like)
 * @param {number} time     when the event happened
 * @param {number} halfLife the time it takes an event's value to halve
 * @returns {number} the event's score, ready to combine with an item's
 */
export function eventScore(value, time, halfLife) {
  if (!(value > 0)) throw new RangeError(`TimeScore values must be greater than 0, not ${value}`);
  return Math.log(value) + time * Math.LN2 / halfLife;
}

/**
 * Two stored scores merged into one, as if one item had had both scores'
 * events: log(e^a + e^b), computed without leaving the log domain.
 *
 * @param {number} a a stored score (EMPTY for none)
 * @param {number} b another stored score with the same half-life
 * @returns {number} the merged score
 */
export function combine(a, b) {
  const high = Math.max(a, b);
  const low = Math.min(a, b);
  if (low === -Infinity) return high;
  return high + Math.log1p(Math.exp(low - high));
}

/**
 * Add an event to an item's stored score.
 *
 * @param {number} logScore the item's stored score (EMPTY if it has none)
 * @param {number} value    the event's value, greater than 0 (1 for a like)
 * @param {number} time     when the event happened
 * @param {number} halfLife the time it takes an event's value to halve
 * @returns {number} the item's new stored score
 */
export function addEvent(logScore, value, time, halfLife) {
  return combine(logScore, eventScore(value, time, halfLife));
}

/**
 * An item's score at a given time, at or after its latest event: the sum of
 * its events' values, each halved for every half-life since it happened.
 *
 * @param {number} logScore the item's stored score
 * @param {number} time     the time to score it at
 * @param {number} halfLife the same half-life its events were added with
 * @returns {number} the item's score at that time
 */
export function scoreAt(logScore, time, halfLife) {
  return Math.exp(logScore - time * Math.LN2 / halfLife);
}
