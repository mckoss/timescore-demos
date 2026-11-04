# TimeScore demos

Live rankings built with [TimeScore](https://mckoss.com/posts/timescore/):
every day's activity counts in full when it happens, then fades with a
half-life. The site shows each source's top movies with a half-life of a day,
a week, a month and a year, and a bar chart race of how the ranking changed
day by day.

The site: **https://mckoss.com/timescore-demos/** (GitHub Pages; mckoss.github.io uses the
mckoss.com domain, so mckoss.github.io/timescore-demos redirects there).

## Sources

| Source | What counts as an event | Collected |
|---|---|---|
| **New IMDb ratings** | A movie's new ratings on IMDb in a day | Daily from IMDb's [non-commercial datasets](https://developer.imdb.com/non-commercial-datasets), from the first run on |
| **TMDB popularity** | A movie's popularity score on [The Movie Database](https://www.themoviedb.org) that day | Daily from TMDB's [daily exports](https://developer.themoviedb.org/docs/daily-id-exports), which go back about three months |

Posters and English titles come from the TMDB API.

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
3. `build/build.py` scores every movie with TimeScore
   ([`collect/timescore.py`](collect/timescore.py)) at the four half-lives and
   writes `site/data/movies.json`. It looks up posters for the movies it
   shows (cached in `data/posters.tsv`).
4. The workflow commits the new data and publishes `site/` to GitHub Pages.

The page shows when the data was last updated. If the daily update fails,
or a source stops getting new data, it says so in an amber box at the top.

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
TMDB_TOKEN=... python3 build/build.py
python3 -m http.server -d site
python3 -m unittest discover -s tests
```

Only the Python standard library is needed.

## Data terms

- Information courtesy of IMDb (https://www.imdb.com). Used with permission.
  IMDb's datasets are for personal and non-commercial use only, so this site
  is non-commercial.
- This product uses the TMDB API but is not endorsed or certified by TMDB.

## License

The code is MIT licensed (see [LICENSE](LICENSE)). The TimeScore algorithm is
in the public domain; a credit is appreciated: "TimeScore algorithm courtesy
Mike Koss".
