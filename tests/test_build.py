"""Tests for the collectors' state files and the TimeScore lists."""

import datetime
import gzip
import os
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
ROOT = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, os.path.join(ROOT, 'collect'))
sys.path.insert(0, os.path.join(ROOT, 'build'))

import build  # noqa: E402
import imdb  # noqa: E402



def day(n):
    return datetime.date(2026, 1, 1) + datetime.timedelta(days=n)


class StateTest(unittest.TestCase):
    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'state.tsv.gz')
            imdb.write_state(path, day(3), {'tt1': 10, 'tt2': 2000})
            self.assertEqual(imdb.read_state(path), (day(3), {'tt1': 10, 'tt2': 2000}))

    def test_no_state(self):
        self.assertEqual(imdb.read_state('/nonexistent/state.tsv.gz'), (None, {}))


class ListsTest(unittest.TestCase):
    def days(self):
        # Old Hit had a huge day long ago; Steady gets a little every day.
        days = []
        for n in range(60):
            events = {'imdb:steady': (10.0, 'Steady')}
            if n == 0:
                events['imdb:old'] = (1000.0, 'Old Hit')
            days.append((day(n), events))
        return days

    def test_short_half_life_favors_recent_activity(self):
        start, titles, lists, racers = build.build_source('imdb', self.days())
        self.assertEqual(start, day(0))
        self.assertEqual(lists['Day'][0]['key'], 'imdb:steady')
        self.assertEqual(lists['Week'][0]['key'], 'imdb:steady')
        # With a year's half-life, the one big day still outweighs.
        self.assertEqual(lists['Year'][0]['key'], 'imdb:old')
        self.assertEqual(racers, {'imdb:steady', 'imdb:old'})

    def test_scores_are_the_faded_sums(self):
        _, _, lists, _ = build.build_source('imdb', self.days())
        steady = next(i for i in lists['Week'] if i['key'] == 'imdb:steady')
        expected = sum(10 * 0.5 ** ((59 - n) / 7) for n in range(60))
        self.assertAlmostEqual(steady['score'], expected, places=1)

    def test_previous_ranks(self):
        _, _, lists, _ = build.build_source('imdb', self.days())
        self.assertEqual(lists['Week'][0]['previous'], 1)


class TrendingTest(unittest.TestCase):
    def test_needs_two_weeks_of_data(self):
        days = [(day(n), {'imdb:steady': (10.0, 'Steady')}) for n in range(build.TRENDING_MIN_DAYS - 1)]
        _, _, lists, _ = build.build_source('imdb', days)
        self.assertNotIn(build.TRENDING, lists)

    def test_steady_activity_is_one(self):
        days = [(day(n), {'imdb:steady': (10.0, 'Steady')}) for n in range(120)]
        _, _, lists, _ = build.build_source('imdb', days)
        self.assertAlmostEqual(lists[build.TRENDING][0]['score'], 1.0, places=2)

    def test_a_surge_trends_above_steady_activity(self):
        days = []
        for n in range(120):
            events = {'imdb:steady': (10.0, 'Steady'), 'imdb:surge': (2.0, 'Surge')}
            if n >= 114:   # the last week, ten times its usual pace
                events['imdb:surge'] = (20.0, 'Surge')
            days.append((day(n), events))
        _, _, lists, _ = build.build_source('imdb', days)
        trending = lists[build.TRENDING]
        self.assertEqual(trending[0]['key'], 'imdb:surge')
        self.assertGreater(trending[0]['score'], 2)
        self.assertAlmostEqual(trending[1]['score'], 1.0, places=2)


if __name__ == '__main__':
    unittest.main()
