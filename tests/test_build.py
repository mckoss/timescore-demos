"""Tests for the collectors, the TimeScore lists and the version check."""

import datetime
import gzip
import json
import os
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
ROOT = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, os.path.join(ROOT, 'collect'))
sys.path.insert(0, os.path.join(ROOT, 'build'))

import build  # noqa: E402
import check_version  # noqa: E402
import imdb  # noqa: E402
import wikipages  # noqa: E402
import wikitopics  # noqa: E402
import wikipedia  # noqa: E402



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


class WikipediaTest(unittest.TestCase):
    def test_only_articles(self):
        for name in ('Main_Page', 'Special:Search', 'Wikipedia:Featured_pictures', 'Portal:Current_events',
                     'File:Example.jpg', 'User_talk:Someone', 'Template:Infobox', '-'):
            self.assertFalse(wikipedia.is_article(name), name)
        for name in ('Taylor_Swift', 'Ramayana:_Part_1', 'Star_Wars:_Episode_IV_–_A_New_Hope', '.xyz'):
            self.assertTrue(wikipedia.is_article(name), name)

    def test_automated_views_are_left_out(self):
        desktop = {'Real': 30_000, 'Desktop_bot': 99_000, 'Other': 2_500}
        all_access = {
            'Main_Page': 4_000_000,
            'Real': 100_000,          # 30% from desktop, like most articles
            'Desktop_bot': 100_000,   # 99% from desktop
            'Phone_bot': 150_000,     # not in the desktop list: at most 2,500 / 150,000 from desktop
            'Small': 10_000,          # not in the desktop list either, but could be 25% from desktop
        }
        kept, dropped = wikipedia.select(all_access, desktop)
        self.assertEqual(kept, [('Real', 100_000), ('Small', 10_000)])
        self.assertEqual(sorted(dropped), ['Desktop_bot', 'Phone_bot'])

    def test_keeps_the_top(self):
        all_access = {f'A{n}': 10_000 + n for n in range(wikipedia.TOP + 50)}
        desktop = {name: views // 3 for name, views in all_access.items()}
        kept, _ = wikipedia.select(all_access, desktop)
        self.assertEqual(len(kept), wikipedia.TOP)
        self.assertEqual(kept[0][0], f'A{wikipedia.TOP + 49}')

    def test_user_agent_names_the_project(self):
        self.assertRegex(wikipedia.USER_AGENT, r'^TimeScoreDemosBot/\S+ \(https://github.com/mckoss/timescore-demos\) ')

    def test_article_entry(self):
        row = {'title': 'Ada Lovelace', 'description': 'English mathematician', 'thumbnail': 'https://x/a.jpg',
               'artist': 'Alfred Chalon', 'license': 'Public domain', 'file_page': 'https://commons/File:A.jpg'}
        self.assertEqual(build.article('wikipedia:Ada_Lovelace', 'Ada Lovelace', row), {
            'title': 'Ada Lovelace', 'image': 'https://x/a.jpg', 'link': 'https://en.wikipedia.org/wiki/Ada_Lovelace',
            'description': 'English mathematician', 'imageCredit': 'Alfred Chalon, Public domain',
            'imagePage': 'https://commons/File:A.jpg'})
        self.assertEqual(build.article('wikipedia:AC/DC', 'AC/DC', None),
                         {'title': 'AC/DC', 'image': None, 'link': 'https://en.wikipedia.org/wiki/AC/DC'})

    def test_page_cache_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'pages.tsv')
            pages = {'wikipedia:A': {'key': 'wikipedia:A', 'title': 'A', 'description': 'Tab\there',
                                     'checked': '2026-11-07'}}
            wikipages.save(pages, path)
            self.assertEqual(wikipages.load(path)['wikipedia:A']['description'], 'Tab here')
            self.assertEqual(wikipages.load(path)['wikipedia:A']['thumbnail'], '')

    def test_people(self):
        life = wikitopics.LIFE_YEARS.search
        self.assertTrue(life('English actor (1940–2026)'))
        self.assertTrue(life('American singer-songwriter (born 1989)'))
        self.assertTrue(life('Persian poet (c. 1207–1273)'))
        self.assertFalse(life('2026 Indian film by Nitesh Tiwari'))
        self.assertFalse(life('Election held in 2026'))

    def test_groups(self):
        groups = wikitopics.groups_of
        self.assertEqual(groups({'topics': 'Culture.Media.Media*:0.89;Culture.Media.Music:0.74', 'person': '1'}),
                         {'people', 'entertainment'})
        self.assertEqual(groups({'topics': 'Culture.Media.Media*:0.83;Culture.Biography.Biography*:0.58'}),
                         {'people', 'entertainment'})
        self.assertEqual(groups({'topics': 'STEM.STEM*:0.94;Culture.Media.Media*:0.86;Culture.Media.Software:0.82'}),
                         {'science'})
        self.assertEqual(groups({'topics': 'Geography.Regions.Americas.North_America:0.99'}), {'places'})
        # Only somewhat about a place, or about a person from one: not a place.
        self.assertEqual(groups({'topics': 'Geography.Regions.Europe.Northern_Europe:0.64'}), set())
        self.assertEqual(groups({'topics': 'Geography.Regions.Asia.South_Asia:0.9', 'person': '1'}), {'people'})
        self.assertEqual(groups(None), set())

    def test_only_what_can_make_a_list_is_tagged(self):
        ranking = [f'wikipedia:A{n}' for n in range(100)]
        # Nothing tagged: everything down to the depth is needed, top first.
        self.assertEqual(wikitopics.needed([ranking], {}, 2)[:3], ranking[:3])
        # Once the top 4 cover every topic twice, nothing further down is needed.
        row = {'person': '1', 'topics': ';'.join(f'{t}:0.9' for t in (
            'History_and_Society.Politics_and_government', 'Culture.Sports', 'Culture.Media.Films', 'STEM.Physics',
            'History_and_Society.Business_and_economics', 'History_and_Society.History'))}
        place = {'person': '0', 'topics': 'Geography.Regions.Oceania:0.95'}
        rows = {ranking[0]: row, ranking[1]: row, ranking[2]: place, ranking[3]: place}
        self.assertEqual(wikitopics.needed([ranking], rows, 2), [])
        # An untagged article above that point is still needed.
        del rows[ranking[1]]
        self.assertEqual(wikitopics.needed([ranking], rows, 2)[0], ranking[1])

    def test_topic_cache_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'topics.tsv')
            wikitopics.save({'wikipedia:A': {'key': 'wikipedia:A', 'person': '1', 'topics': 'Culture.Sports:1.00',
                                             'checked': '2026-11-07'}}, path)
            self.assertEqual(wikitopics.groups_of(wikitopics.load(path)['wikipedia:A']), {'people', 'sports'})

    def test_topic_lists(self):
        now = [(f'wikipedia:A{n}', 100.0 - n) for n in range(60)]
        before = [key for key, _ in reversed(now)]
        pools = {'Week': (now, before)}
        sporty = {key: {'sports'} for key, _ in now[::2]}
        lists = build.topic_lists(pools, sporty)
        self.assertEqual(list(lists), ['sports'])
        week = lists['sports']['Week']
        self.assertEqual(len(week), build.SHOWN)
        self.assertEqual([item['key'] for item in week[:3]], ['wikipedia:A0', 'wikipedia:A2', 'wikipedia:A4'])
        self.assertEqual(week[0]['previous'], 30)    # the order was reversed the day before
        self.assertEqual(week[-1]['previous'], 8)
        # A topic with fewer than TOPIC_MIN articles isn't shown.
        self.assertEqual(build.topic_lists(pools, {now[0][0]: {'sports'}}), {})

    def test_pools(self):
        pools = {}
        days = [(day(n), {'wikipedia:A': (10.0, 'A'), 'wikipedia:B': (float(n), 'B')}) for n in range(5)]
        build.build_source('wikipedia', days, pools)
        self.assertEqual(sorted(pools), ['Day', 'Month', 'Week', 'Year'])
        now, before = pools['Day']
        self.assertEqual([key for key, _ in now], ['wikipedia:A', 'wikipedia:B'])
        self.assertEqual(set(before), {'wikipedia:A', 'wikipedia:B'})

    def test_series_files(self):
        days = [(day(n), {'wikipedia:A': (10.0 + n, 'A'), **({'wikipedia:Café': (5.0, 'Café')} if n else {})})
                for n in range(3)]
        with tempfile.TemporaryDirectory() as tmp:
            build.write_series(days, day(0), tmp)
            files = sorted(os.listdir(tmp))
            self.assertEqual(len(files), build.SERIES_SHARDS + 1)
            with open(os.path.join(tmp, f'series-{build.shard_of("wikipedia:Café"):03d}.json'), encoding='utf-8') as f:
                shard = json.load(f)
            self.assertEqual(shard['start'], '2026-01-01')
            self.assertEqual(shard['series']['Café'], [[1, 5.0], [2, 5.0]])
            with open(os.path.join(tmp, 'index.json'), encoding='utf-8') as f:
                self.assertEqual(json.load(f), ['A', 'Café'])
        # The same hash as app.js shardOf (checked there against these values).
        self.assertEqual([build.shard_of(k) for k in ('wikipedia:Black_hole', 'wikipedia:Café')], [104, 44])

    def test_credit_is_plain_text(self):
        self.assertEqual(wikipages.plain('<a href="//commons.wikimedia.org/wiki/User:X">X &amp; Y</a>\n'), 'X & Y')


class VersionTest(unittest.TestCase):
    LOG = '## [1.2.0] - 2026-11-07'

    def test_data_only_changes_need_no_new_version(self):
        self.assertEqual(check_version.problems(['data/tmdb/2026-11-07.tsv', 'site/data/movies.json'],
                                                '1.1.0', '1.1.0', ''), [])

    def test_code_changes_need_a_higher_version(self):
        self.assertTrue(check_version.problems(['site/app.js'], '1.2.0', '1.2.0', self.LOG))
        self.assertTrue(check_version.problems(['site/app.js'], '1.2.0', '1.1.9', self.LOG))
        self.assertEqual(check_version.problems(['site/app.js'], '1.1.0', '1.2.0', self.LOG), [])

    def test_versions_compare_as_numbers(self):
        self.assertEqual(check_version.problems(['build/build.py'], '1.9.0', '1.10.0', '## [1.10.0]'), [])

    def test_the_changelog_needs_an_entry(self):
        self.assertTrue(check_version.problems(['site/app.js'], '1.1.0', '1.2.0', '## [1.1.0]'))

    def test_the_version_must_be_semver(self):
        self.assertTrue(check_version.problems(['site/app.js'], '1.1.0', 'v1.2', '## [v1.2]'))


if __name__ == '__main__':
    unittest.main()
