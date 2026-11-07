# Changelog

Each code change gets a new version number, following
[Semantic Versioning](https://semver.org): a new feature raises the middle
number, a fix or a change behind the scenes raises the last one, and a
change that breaks how the site or its data files work raises the first.
Data the daily workflow commits isn't versioned. The current version is in
[VERSION](VERSION), shown in the site's footer and tagged in git (`v1.6.1`).

## [1.10.0] - 2026-11-07
### Added
- A search box on the Wikipedia tab: chart the history of any English
  Wikipedia article, not just those in the lists. Suggestions come from
  Wikipedia's title search, and the chart gets the article's views for
  every day from Wikimedia's Pageviews API, in the reader's browser.
- If Wikimedia doesn't answer, the page falls back to this site's own data:
  the search looks through every article the site has collected, and the
  chart uses the days an article was among the 500 most read, marked
  "top-500 days only". The build writes that data for every article in
  `site/data/wikipedia/` (128 small files loaded as needed, and an index);
  it's rebuilt on each deploy and not committed.

### Changed
- Wikipedia's lines on the history chart use every day's views from
  Wikimedia (when it answers), for listed articles too, so all lines are
  measured the same way.

## [1.9.0] - 2026-11-07
### Changed
- Lists show the top 20 (they showed 10), with 3 more fading out below.
- Wikipedia topics rank every article in the data, not just each
  half-life's top 300, so rarer topics fill up: History & military and
  Places now show too. Only the articles that could make a topic's list get
  tagged: the build walks each half-life's ranking from the top and stops
  once every topic's list is settled (at most 5,000 deep), 3 requests at a
  time, up to 10 minutes a run. A topic shows once it has 5 articles in
  every half-life's list (it was 10).
- Topics are kept in their own cache, `data/wikipedia-topics.tsv`, apart
  from the descriptions and images of the articles shown.
- The history button says "History" (on wider screens), and the note under
  each top list says what it does.

## [1.8.0] - 2026-11-07
### Added
- Topics on the Wikipedia tab: People, Politics, Sports, Entertainment,
  Science & tech, Business, History and Places, each with its own top
  articles at every half-life, picked from each half-life's top 300.
  Topics come from Wikimedia's article topic model; People comes from
  Wikipedia's "Living people" category and biographies' short
  descriptions ("English actor (1940–2026)"). A topic shows once it has at
  least 10 articles in every half-life's list.
- A history chart for any movie or article: the chart button beside each
  one in the top and trending lists adds its line (up to 8), showing its
  TimeScore on every day of the data at the half-life chosen for the top
  list, with a readout of every line on the day under the pointer.

### Changed
- `site/data/movies.json` gives each source's daily values as `series`
  for every item it shows, and the race's items as `racers` (they were
  `race`).

## [1.7.1] - 2026-11-07
### Fixed
- The Wikipedia collector tries a day again when Wikimedia says it has no
  list for it, which sometimes happens for days it has published, and says
  in the log when it skips a day. The first run missed 8 of 98 days this way.

## [1.7.0] - 2026-11-07
### Added
- A Wikipedia pageviews tab: English Wikipedia's most-read articles from the
  Wikimedia Pageviews API (CC0), ranked with TimeScore like the movies, with
  each article's short description and free image (with its author and
  license, linked to its page on Wikimedia Commons). Pages that aren't
  articles (the Main Page, searches, portals) and pages whose views look
  automated (nearly all or nearly none from desktop computers) are left out.
- The daily update collects Wikipedia's newest days, then fills in the
  history up to 90 days a run, back to November 2023.
- Wikipedia on the update log: its coverage, totals and what each update added.

### Changed
- A long race plays faster, so it takes about a minute at most.
- `site/data/movies.json` lists each source's `items` (it was `movies`), each
  with an `image` (it was `poster`).

## [1.6.1] - 2026-11-07
### Changed
- The site is called TimeScore Demos (it was TimeScore Movie Charts), in
  both pages' titles and headings.

## [1.6.0] - 2026-11-07
### Changed
- The charts page shows one source at a time, picked with a tab for each
  source at the top that says how many days of data it has. TMDB comes first
  and is shown by default, since it has the most history; the choice is in
  the page's address (#tmdb, #imdb), so it can be linked to.

## [1.5.1] - 2026-11-07
### Changed
- The version shows as a small "v1.5.1" under each page's title, linked to
  this changelog, in place of the line in the footer.

## [1.5.0] - 2026-11-07
### Added
- Version numbers: `VERSION`, this changelog, the version in each page's
  footer and in each entry of the update log, and a git tag for each version
  merged to `main`.
- A check on pull requests that a code change raises the version and adds it
  to this changelog.

## [1.4.2] - 2026-11-07 (#9)
### Changed
- Switching half-lives slides the rankings in 1 second instead of 5.

## [1.4.1] - 2026-11-07 (#8)
### Changed
- Movies slide to their real rank when they enter or leave the top 10,
  through a fading zone that shows #11 to #13, instead of fading out.

## [1.4.0] - 2026-11-07 (#7)
### Changed
- The Day, Week, Month and Year lists became one Top movies list per source
  with a half-life selector; switching slides each movie to its new rank.

## [1.3.1] - 2026-11-07 (#6)
### Fixed
- A browser could pair a new page with old scripts from its cache and show
  an empty page. Each deploy now stamps its commit on the scripts' URLs.

## [1.3.0] - 2026-11-07 (#5)
### Added
- The update log's health banner (green when running as expected, red when
  an update is missed), a 60-day coverage chart and a chart of the data's
  size.

## [1.2.0] - 2026-11-07 (#4)
### Added
- The update log page, with totals and a row for each update, and
  `data/log.jsonl`, rebuilt from history for the updates before it.
### Changed
- Weekly trending waits for 14 days of a source's data.

## [1.1.1] - 2026-11-07 (#3)
### Added
- Tests and a build check on every pull request.

## [1.1.0] - 2026-11-04 (#2)
### Added
- Weekly trending: each movie's Week score divided by its Month score,
  rescaled so 1.0 is its usual pace.

## [1.0.0] - 2026-11-04 (#1)
### Added
- TimeScore Movie Charts: daily IMDb and TMDB collectors, Day, Week, Month and
  Year lists, a bar chart race per source, posters from TMDB, a freshness
  line, and the daily workflow that collects, builds and publishes.
