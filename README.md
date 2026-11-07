# TimeScore demos

Live rankings built with [TimeScore](https://mckoss.com/posts/timescore/):
every day's activity counts in full when it happens, then fades with a
half-life. The site shows each source's top movies or articles with a half-life of a day,
a week, a month and a year (Wikipedia's also by topic), a bar chart race of
how the ranking changed day by day, and a history chart of any movies or
articles you pick.

The site: **https://mckoss.com/timescore-demos/** (GitHub Pages; mckoss.github.io uses the
mckoss.com domain, so mckoss.github.io/timescore-demos redirects there).

## Sources

| Source | What counts as an event | Collected |
|---|---|---|
| **New IMDb ratings** | A movie's new ratings on IMDb in a day | Daily from IMDb's [non-commercial datasets](https://developer.imdb.com/non-commercial-datasets), from the first run on |
| **TMDB popularity** | A movie's popularity score on [The Movie Database](https://www.themoviedb.org) that day | Daily from TMDB's [daily exports](https://developer.themoviedb.org/docs/daily-id-exports), which go back about three months |
| **Wikipedia pageviews** | An English Wikipedia article's views that day | Daily from Wikimedia's [Pageviews API](https://doc.wikimedia.org/generated-data-platform/aqs/analytics-api/reference/page-views.html), back to November 2023 |

Posters and English titles come from the TMDB API. Wikipedia articles' short
descriptions and free images come from Wikipedia's API.

## How it works

A GitHub Actions workflow, [`.github/workflows/daily.yml`](.github/workflows/daily.yml),
runs every day at 09:41 UTC (and can be run by hand from the Actions tab):

1. `collect/imdb.py` downloads IMDb's current vote counts and compares them
   with the previous day's snapshot to find each movie's new ratings. It
   commits only the top 500 movies of the day to `data/imdb/YYYY-MM-DD.tsv`.
   The full snapshot stays in the Actions cache, not in the repository,
   because IMDb's terms don't allow republishing its data.
2. `collect/tmdb.py` downloads any TMDB daily exports not yet collected and
   commits the top 500 movies of each day to `data/tmdb/YYYY-MM-DD.tsv`.
3. `collect/wikipedia.py` downloads Wikimedia's daily list of the 1,000
   most-viewed English Wikipedia pages, and the same list for desktop
   computers alone, and commits the top 500 articles of each day to
   `data/wikipedia/YYYY-MM-DD.tsv`. It leaves out pages that aren't articles
   and pages whose views look automated: real readers come about a third from
   desktop, so a page with more than 90% or less than 3% of its views from
   desktop is left out (each day's file lists them). Each run collects the
   newest days, then up to 90 older ones, until it has every day since
   November 1, 2023. It identifies itself as Wikimedia asks
   (`TimeScoreDemosBot/<version> (https://github.com/mckoss/timescore-demos)`),
   paces its requests and waits when told to.
4. `build/build.py` scores every movie and article with TimeScore
   ([`collect/timescore.py`](collect/timescore.py)) at the four half-lives and
   writes `site/data/movies.json`. It looks up posters for the movies it
   shows (cached in `data/posters.tsv`), and the descriptions and free images
   of the articles (cached in `data/wikipedia-pages.tsv`), using only freely
   licensed images, never English Wikipedia's fair-use posters and logos.
   It also sorts the articles into topics: People, Politics, Sports,
   Entertainment, Science & tech, Business, History & military and Places
   (`build/wikitopics.py`, cached in `data/wikipedia-topics.tsv`). The
   topics come from Wikimedia's
   [article topic model](https://api.wikimedia.org/wiki/Lift_Wing_API/Reference/Get_articletopic_outlink_prediction),
   one request per article. Only articles that could make a topic's top 20
   get tagged: the build walks each half-life's ranking from the top until
   every topic's list is settled. People comes from Wikipedia's "Living
   people" category and biographies' short descriptions instead, since the
   model tags what an article is about rather than whether it is about a
   person.
5. The workflow commits the new data and publishes `site/` to GitHub Pages.

Pull requests run [`.github/workflows/tests.yml`](.github/workflows/tests.yml):
the unit tests and a build of the site from the data already in the repository.

The [update log](https://mckoss.com/timescore-demos/status.html) shows each run: when it
ran, what started it, and the data each source added. `build/log.py` adds each
run to `data/log.jsonl` and writes `site/data/status.json` for that page.

The page shows when the data was last updated. If the daily update fails,
or a source stops getting new data, it says so in an amber box at the top.

## Versions

Each code change raises the version in [`VERSION`](VERSION), following
[Semantic Versioning](https://semver.org), and adds an entry to
[`CHANGELOG.md`](CHANGELOG.md): a new feature raises the middle number, a
fix or a change behind the scenes the last one, and a change that breaks how
the site or its data files work the first. The check on pull requests
(`build/check_version.py`) fails a code change that doesn't. The daily
workflow tags each version in git (`v1.5.0`) when it first reaches `main`,
each page shows it under its title, and the update log records the version each
update ran.

## Setup

1. **Pages:** Settings → Pages → Build and deployment → Source: **GitHub Actions**.
2. **Posters:** create a free [TMDB](https://www.themoviedb.org/signup) account,
   copy its *API Read Access Token* from Settings → API, and add it as a
   repository secret named `TMDB_TOKEN` (Settings → Secrets and variables →
   Actions). Without it the site works, with gray boxes in place of posters.
3. Run the workflow once from the Actions tab (Daily update → Run workflow).
   IMDb rankings start the day after the first run, once there are two
   snapshots to compare.

## Run it locally

```sh
python3 collect/imdb.py      # needs ~300 MB of downloads; first run saves a baseline
python3 collect/tmdb.py
python3 collect/wikipedia.py --start 2026-10-01
TMDB_TOKEN=... python3 build/build.py
python3 -m http.server -d site
python3 -m unittest discover -s tests
```

Only the Python standard library is needed.

## Data terms

- Information courtesy of IMDb (https://www.imdb.com). Used with permission.
  IMDb's datasets are for personal and non-commercial use only, so this site
  is non-commercial.
- This product uses the TMDB API but is not endorsed or certified by TMDB. The site
  shows TMDB's logo (`site/tmdb-logo.svg`, from TMDB's
  [logos page](https://www.themoviedb.org/about/logos-attribution)) next to this notice.
- Wikipedia pageview data is from the Wikimedia Foundation, released under
  [CC0](https://creativecommons.org/publicdomain/zero/1.0/). Article images
  come from Wikimedia Commons and Wikipedia under their free licenses; each
  links to its page, and the site names its author and license.

## License

The code is MIT licensed (see [LICENSE](LICENSE)). The TimeScore algorithm is
in the public domain; a credit is appreciated: "TimeScore algorithm courtesy
Mike Koss".
