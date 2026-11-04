# Changelog

## 2026-11-04 (the commit name really shows now)

Renaming the committer was not enough: GitHub prints a commit's author **account**, and it finds that
account by the author e-mail. The built-in bot's address always resolves to `github-actions[bot]`, so the
history still said that whatever the name was.

* The default author address is now `thishcrvwqe-bot@users.noreply.github.com`, which belongs to no
  account - GitHub therefore prints the git name, **`thishcrvwqe-bot`**.
* If the push is rejected (some repository policies only accept the bot as the author), the step retries
  once as `github-actions[bot]` and says so in the log. Losing the bookkeeping would be worse than a
  bot-looking name.

## 2026-11-04 (the database commit has a name now)

Every run commits `data/sync-state.json`, and the history said `github-actions[bot]` - which says nothing
about what happened. The commit is now made as **`thishcrvwqe-bot`**.

* `vars.COMMIT_NAME` (default `thishcrvwqe-bot`) and `vars.COMMIT_EMAIL` (default the built-in bot's
  address) control it, and the run log prints the committer it used.
* The email has to stay the bot's: GitHub only accepts a push from the workflow's built-in token when the
  commit is attributed to that account. To use a personal address instead, the push needs a personal access
  token - not needed for this.

## 2026-11-04 (credit splitting fix behind the 17 wasted `REVERSED` searches)

The first clean live run showed `REVERSED` spending **17 real queries and winning nothing**, and
`--stats` listing `TOPRESULT` as "tried but never won" while giving it no row at all. Both were real bugs:

* **"MC X" was split into "MC"** - the collaboration splitter treats a lowercase ` x ` as "and", so a name
  ending in a lone letter (`MC X`, `DJ X`) became `MC` / `DJ`, a search term no Spotify artist has. The
  letter is now held together before the split, so `MC X & DJ Y` is `["MC X", "DJ Y"]` and `DJ NEO x MC X` is
  `["DJ NEO", "MC X"]`, while a real collaboration (`A x B`) still splits.
* **A track credited to the whole collaboration looked like a conflict** - Spotify often keeps
  `MC X & DJ Y` in one artist name; neither half matched the joined string, so the correct track was
  rejected. `shared_credit()` now also compares the *words inside* a credit, and strips stray punctuation
  and spacing on both sides. A genuinely different artist is still a conflict.
* **`--stats` now gives a row to every step that was tried**, even when all its queries came from the run
  cache (they show as `cached`). Before, `TOPRESULT` appeared in the "tried but never won" line with no row
  above it.

`MATCHER_VERSION` is now **14**, so the remembered skips get one more try under the fixed rules. Tests:
**246**.

## 2026-11-04 (`--reset-db`: the emergency switch)

A way to throw the bookkeeping away without touching the playlist:

* **`--reset-db history|playlist|all`** - `history` drops only the statistics (`matched` / `worked` / `ran`)
  and the matcher stamp, `playlist` drops one playlist's record, `all` empties the database.
* **Spotify is never touched**: a reset only forgets what the sync already did, so the next run searches the
  whole playlist again and re-adds what is missing.
* **`--yes` is required** to apply it; without it the command prints exactly what it would drop and changes
  nothing. A copy is kept as `data/sync-state.json.bak` (`--no-backup` to skip it).
* In the Actions tab the same thing is a `reset_db` choice input on **Run workflow**; it runs before the sync
  (so one run rebuilds the database) and stays a preview while the dry-run box is ticked.

Tests: **241**.

## 2026-11-04 (summary fixes after the first live run)

The first real run added 158 tracks. Its summary then raised three fair questions, all of them display or
bookkeeping problems rather than matching problems:

* **`matched 316` beside `saved 158`** - the tally is the whole history and the dry run that previewed the
  live run counted too. The line now says so: `matched 316 (all runs so far, dry runs included)`.
* **`DURATION`: 4 songs found, `—` queries** - those searches came from the run cache, so no new request was
  sent. A dash read as "this step did nothing"; it now says `cached`.
* **Steps that ran but never sent a new query were listed as "Never tried"** - a step that was tried (cache
  hits, or a query it could not build) now goes to "Tried but never won" instead of the "leave it alone" list.

Also fixed: **a live run that added no song wrote no state file at all**, so its skip/failure counters (and
the summary built from them) were lost. The bookkeeping is now saved immediately in a live run and deferred
to the end of a dry run, so a preview still changes nothing.

Tests: **234**.

## 2026-11-04 (`--stats` tells "never won" apart from "never ran")

The first live run showed why the tally was misleading: it counted only the step that *won* each song, so
26 of 29 steps read as "Never matched" - including ones that search on every single song and simply lose to
an earlier step.

* Every run now also records **how many queries each step actually sent** (`worked`) and **how many songs it
  was tried on** (`ran`), next to the existing `matched` count.
* `--stats` shows a **Queries sent** column and splits the closing line into
  **Tried but never won** (real candidates for removal) and
  **Never tried (its condition never applied to these videos)**, which must not be pruned.
* `MANUAL` is labelled as a manual pick instead of an extra step.

Tests: **229**.

## 2026-11-04 (`ISRC` step: exact recording identity)

The description parser already read `ISRC: …`; it is now **used**:

* **`ISRC` (new step 23)** - when the description states an ISRC, the candidate queries are turned into
  track **IDs** (cheap, no metadata), each ID is read once, and the track whose `external_ids.isrc` equals
  it wins. An ISRC identifies the *recording*, so no title, version or artist check is needed.
* Limits kept: at most 8 candidates per query, one query is enough when it works, and a query whose
  candidates carry no ISRC at all is abandoned instead of being retried - no bursts.
* The full track lookup keeps `isrc`, and `search_ids()` was added so the step can look at candidates
  without paying for metadata it will not use.

Deliberately **not** done: downloading audio and comparing fingerprints. It needs a large dependency,
minutes of CPU per song and extra hosting, and it answers the same "is this the right recording" question
that the ISRC answers exactly - whenever the upload states one. The relaxed steps (`DURVER`, `TITLEONLY`,
`DESCTEXT`) still refuse when the evidence is thin.

Chain is **29** steps, `TOPRESULT` last. `MATCHER_VERSION` is now **13**. Tests: **228**.

## 2026-11-04 (`--stats`: which step earns its place)

Every run now tallies the method that found each song in the playlist database (`matched`), and
`--stats` prints it as a table: songs per method, their share, and the steps that never matched. The same
table is appended to the Actions job summary, so the decision "keep or drop a step" can be made from data
instead of one run's line.

* The tally is written with the run's own database save (no extra file churn), and a dry run does not
  change it - a dry run only keeps skip/failure bookkeeping.
* `step_stats()` / `record_match()` keep it a plain `{code: count}` dict, so hand-editing
  `data/sync-state.json` stays easy.

Tests: **224**.

## 2026-11-04 (a richer description parser)

More of what uploads already write in the description is now read, so videos whose title is marketing text
are matched without guessing:

* **`Song name: …` / `Track: …` / `Title: …`** as well as `Song: …`.
* **`Prod. by DJ NEO` / `Prod: …` / `Produced by …` / `Producer: …` / `Music by …`** are read as an artist
  credit: a track credited to the producer is no longer a conflict (phonk uploads often name only that
  producer), while the producer alone never makes a *different* artist acceptable.
* **`ISRC: …`** is read for evidence only (Spotify search has no ISRC field), and a description that is a real
  release page no longer has to be guessed from its wording.
* **`DESCTEXT` (new step 23)** - a short line with no label at all (`MONTAGEM MIAU`) is tried as the song
  name, with the producer/channel as the artist, a **0.92** floor, and calls to action
  ("Subscribe …", "Listen …"), links, hashtags and genre words skipped entirely.

The chain is **28** steps and `TOPRESULT` is still last. `MATCHER_VERSION` is now **12**. Tests: **221**.

## 2026-11-04 (weekly retry of skipped songs)

The schedule now has a second cron: **Sunday 03:00 UTC** (`0 3 * * 0`). Only that run sets `RETRY_SKIPPED`,
and only then does `sync()` release the remembered skips older than **`RETRY_AFTER_DAYS` (7)** days and search
them once more:

* a track that came back to Spotify (copyright removal reversed) is added with no manual step,
* a video that turned public is already handled by `changed_video()` on any run,
* a song that misses again is **counted but not reported** - the retry costs the reader nothing,
* a match is always reported (it is an ADD).

The six 4-hourly runs are unchanged, so a manual report is still not repeated the next hour.
`--retry-expired` lists what the next weekly run would release (read-only), and skip entries now carry `at`
(the time they gave up) next to `since`; entries written before this change count as expired once.

Tests: **212**.

## 2026-11-04 (a skip is reported once, and can be retried)

A run after the rule bump re-reported the same two songs (DESTELLO, LOUCARA) and offered their pick links
again - even though one of them no longer exists on Spotify and the other video is private. Fixed:

* **A re-tried skip is counted but never reported.** When `MATCHER_VERSION` changes, remembered skips get
  one more try. If the song still does not match, the event is marked quiet: it stays in `Skipped: N` but
  never reaches Telegram, and no pick link is offered twice. Reading `Skipped: 7 → 3` was misleading; the
  log now says which songs were re-tried instead.
* **A video whose title appeared is searched again.** A private/unreadable video was remembered under
  "Private video"; once it is public the remembered skip no longer hides it (`changed_video()`).
* **`--forget-video <id>` / `--forget-skipped`.** The only supported way to give a remembered skip another
  try, instead of editing `data/sync-state.json` by hand. `skipped` entries now also carry `since` (the
  matcher version that gave up) and `retried`.
* **A title that repeats the song name is one song.** "MONTAGEM MIAU (MONTAGEM MIAU)" picked up a false
  `mix` version token from the second "MONTAGEM", so a correct match was refused; `unduplicate()` drops the
  repeated half before parsing, and `versions_agree()` compares a repeated name once.

`MATCHER_VERSION` is now **11**. Tests: **209**.

## 2026-11-04 (two ways for videos whose title is not the song)

A real run showed two kinds of upload the title cannot identify:

* **`LINKED` (16)** - the uploader pasted the track into the description
  (`open.spotify.com/track/<id>`). The track is read **directly** (one Web API call, no search) and the only
  check left is the version: a `(Slowed)` video is refused a plain track and the other way round.
* **`SONGTAG` (22)** - the title is marketing (`MONTAGEM MIAU 🔥`) and the song is named in the
  description: `Song: …` / `Track: …`, `Artist: …`, YouTube's `♪ Song`, a quoted name, or the uploader's
  hashtags and tags (`#MontagemMiau` → `Montagem Miau`, genre words skipped). The name is searched with
  the stated artist (else the uploader) and must reach **0.90** title similarity, with the version and the
  artist checks intact.

Both are ordinary steps in the chain (nothing was removed), so `TOPRESULT` is still last - the chain is
**27** steps. `youtube()` now also keeps `snippet.tags`, which the same API call already returns.

`MATCHER_VERSION` is now **10** (remembered skips get one more try). Tests: **199**.

## 2026-11-04 (rate limit: fewer, slower, cached searches)

The five new steps work, but each one can cost several searches, so a run is now careful with them:
run fewer, cache exact, pause between, and slow down only when Spotify says so.

* **One request per distinct query.** `search_query()` caches its answer for the run (case and spacing
  insensitive, bounded by `SEARCH_CACHE_MAX`), so two steps asking "nulteex shaka" and "shaka" pay for it
  once. The log line at the end says how much the cache saved: `Spotify searches: 41 real query(s), 17
  reused from the run cache`.
* **Extra steps only for songs the classic methods missed.** Already the case, and now pinned by tests:
  a `STRICT` hit, or a song that is already in the playlist, sends **zero** extra queries.
* **A gap between searches, and a wider one when Spotify complains.** `SEARCH_PAUSE_SECONDS` (default
  `0.5 s`, on top of `REQUEST_DELAY_SECONDS`) separates two real searches. After an HTTP **429** the gap
  doubles for the rest of the run, up to 30 s — on top of the existing `Retry-After` / exponential retry
  of read requests.
* **A dead session no longer burns the chain.** A `FatalError` (blocked cookie, 403, changed web-player
  operation) used to be treated like one failed query, so all 25 steps were spent on the same error. It
  now stops the chain immediately and fails the run loudly, as it should.

`MATCHER_VERSION` stays **9** (no matching rule changed). Tests: **186**.

## 2026-11-04 (five more ways to find a song)

The existing steps are untouched; five **new** steps were inserted before the loosest ones, so the chain is
now 25 steps and `TOPRESULT` is still last.

| # | Code | What it does | Example |
|---|---|---|---|
| 16 | `FIELD` | Spotify field search: `track:"SHAKA" artist:"Nulteex"` (with a plain `track:` retry) | collab uploads |
| 17 | `VARIANTS` | three query shapes at once: artist+title+version, artist+title, title+version | `SHAKA (SLOWED)` |
| 18 | `DURVER` | a looser title is enough when the length is within ±3 s **and** the version agrees | `LOUCARA FUNK!` |
| 19 | `CLEANARTIST` | clean the title first, then use the artist left over | `DESTELLO - HDN \| VIRAL PHONK` |
| 20 | `TITLEONLY` | title only, accepted only when the length proves it and the track name sits inside the title | `MONTAGEM RUNE - WUYS x KIT` |

### The report now hands over a manual pick

Each skipped song in the full log gets a ready Spotify search link plus the exact key for
`data/track-overrides.json`, so a song that really is missing (or spelled oddly) can be added by hand once
and is then added directly on every later run:

```
#1 SKIP: DESTELLO - HDN | VIRAL PHONK — youtu.be/aLZNbOUOyI4 · No confident artist/title/version match
   pick: https://open.spotify.com/search/DESTELLO%20-%20HDN%20%7C%20VIRAL%20PHONK  →  track-overrides.json: "aLZNbOUOyI4": "<track id>"
```

At most **five** links per run (`PICK_LINKS_PER_RUN`), because the message cap still has to hold.

### Two bugs found while wiring these in

* `artist_ok()` returned `True` for any track when the title carried no credit at all — the channel name was
  never checked, so `CHANNEL`/`UPLOADER` could accept a different artist's track that merely shared the
  channel name. The uploader's name is now the last artist hint and is checked like any other (placeholder
  channels such as `Uploader` / `Music` prove nothing).
* `version_ok()` only looked at the track name. Spotify often keeps the version on the **album**
  (`SHAKA` on `SHAKA (Slowed)`), so that is used as a fallback. Version checking also reads the video title
  now, so a parse that swallowed the version ("SHAKA - Slowed" → artist `SHAKA`, song `Slowed`) cannot let
  the plain original through.

`MATCHER_VERSION` is now **9**. Tests: **173**.

## 2026-11-04 (Label Engine credit lines, and null artists)

A distributor like Label Engine writes the credit in **two different lines**:

```
Provided to YouTube by Label Engine

SHAKA (SLOWED) · Nulteex · ewyx      ← song (with the version) · artist · artist

SHAKA                                ← the plain song title

℗ INTERTONE

Released on: 2026-10-16

Producer: Ion Purice

Composer: Ilia Khmaladze

Auto-generated by YouTube.
```

* The credit line is read as `Nulteex, ewyx` and a **plain song line straight after it** is not mistaken for
  an artist. `Producer:` / `Composer:` / `Lyricist:` lines use real names and are never searched.
* **One credited artist is enough.** `artist_ok` asks "does any artist the video credits appear on this
  track?", so Spotify having only `Nulteex` (not `ewyx`) matches; a track credited only to `Somebody` is
  refused, because that contradicts the credit.
* Short forms agree: `Nulteex` ↔ `Nulteex Music`.
* `REVERSED` and `SINGLE` (the two collab steps) now apply the same artist and title checks as every other
  step, and `CHANNEL`/`UPLOADER` no longer accept a track whose artist contradicts the credit just because
  the channel name was found in it.

### A null artist name no longer breaks a run

Spotify can return an artist slot with `"name": null`. `normalized()` returned a non-string and joining it
crashed **every** extra step with `TypeError`. Now such a slot is dropped at the source (never kept in a
track's artist list) and `normalized()` returns `''` for anything that is not a string, so a missing name is
neither an artist nor a conflict.

`MATCHER_VERSION` is now **8**. Tests: **161**.

## 2026-11-04 (description credits + featured names)

### The artist credit in the description is used now

Distributor uploads ("Provided to YouTube by …") put the artist in the description, never in the title:
`FUNK TONTO (feat. Mc Ombrinho) [Slowed]` on `Raiden - Topic`. The parser read `Raiden` as the artist, so
the real track was refused. Now:

* the `Song · Artist · Artist` line of the description is read when its song part is the start of the video
  title (`FUNK TONTO` + `(feat. …) [Slowed]`), and the video title is kept as the song, so the version words
  and the `feat.` credit are still there;
* `artist ok` accepts the description's artists when the title credits nobody - so a description upload can
  match a `STRICT` search, which is what makes the *first* method work for these channels;
* a description line about a **different** song is still ignored, and a wrong artist in the description is
  still refused.

### A featured credit is not part of the song title

`FUNK TONTO (feat. Mc Ombrinho) [Slowed]` and Spotify's `FUNK TONTO` (featured name credited separately) or
`FUNK TONTO, Pt. 2 (feat. Mc Ombrinho)` are the same song. `name_matches`/`same_song_title` now drop the
`(feat. …)` / bare `feat. …` block (keeping the version words, so a mixed edit is still refused).

`MATCHER_VERSION` is now **7**. Tests: **154**.

## 2026-11-04 ("Release - Topic" pages and the slowed ladder)

### A "… - Topic" page is never the song

`MONTAGEM GALACTO LOCONA (Ultra Slowed)` on **Release - Topic** was being read as artist `Release`, song
`MONTAGEM …` - so every query carried a fake artist and `artist_ok()` refused the right track.

* A **named** Topic page is an artist: `HDN - Topic` → artist `HDN` (unchanged, plus the `- Topic` suffix is
  stripped from the search term itself).
* A **compilation** Topic page says nothing: `Release - Topic`, `Releases - Topic` → no artist credit, so the
  title is the song and the extra steps search it alone - the version and the title are still checked exactly
  as before. A channel name with `release`/`releases` in it can no longer become a search term.

### The slowed ladder in the `SLOWED` step

Spotify often has only one rung of the ladder. `SLOWED` now accepts the same song at another rung
(`Slowed` for an `Ultra Slowed` video) - never the original, a remix or a sped-up edit - and still refuses
when two *different* rungs come back.

`MATCHER_VERSION` is now **6**. Tests: **146**.

## 2026-11-04 (BROKEN + the run that went red)

### Step 20: `BROKEN` - a title whose dash halves are swapped

`DESTELLO - HDN | VIRAL PHONK` was read as artist `DESTELLO`, song `HDN`, but the upload was the other way
round (`HDN` is the artist, `DESTELLO` is the song). `BROKEN` searches it swapped - and only accepts when
the swapped half is an artist Spotify credits **and** the uploader's own name, so it cannot invent a match.

### The uploader's decoration is no longer part of the artist name

`HDN🎹`, `HDN Music`, `Raiden - Topic` are searched as `HDN`, `Raiden`; a pasted filename dot (`Signals.`)
is not treated as a domain, so the name stays `Signals`. A channel name with nothing left (`★☆`) is not used
as a search term. This was silently changing every query the `CHANNEL`/`TOPIC` steps made.

### The red ✗ after a good run was the database push

Run #6 added/reported everything, then failed in **Save sync database** - the last step - because `main`
had moved during the 14-minute run, so `git push` was rejected. Consequences: the run is marked failed, and
the bookkeeping (which drives `MATCHER_VERSION` retries) never lands. Now the step rebases the one-file
commit first, and a rejected push is a `::warning::` instead of a job failure - the sync itself already
finished.

`MATCHER_VERSION` is now **5**. Tests: **139**. Report note: `Matched by extra step:` only lists the extra
steps, so a run where every song matched with `STRICT`/`LOOSE` shows nothing there - the per-song line
carries `· STRICT ·` / `· LOOSE ·` either way.

## 2026-11-04 (ALBUM / PART / POPULAR + `--explain`)

### Three more steps (then 19 in total) - for the songs that Spotify *does* have

Run #5 skipped 7 songs; 6 of them are on Spotify, our checks simply refused every search result:

| # | Code | What it does | Example |
|---|---|---|---|
| 16 | `ALBUM` | the version/naming lives on the **album** (`X - Single`, `X (Slowed)`) | `FUNK TONTO (Slowed)` album |
| 17 | `PART` | Spotify splits a song into `Pt. 1` / `Pt. 2` - still the same song | `FUNK TONTO, Pt. 2 (feat. Mc Ombrinho)` |
| 18 | `POPULAR` | one title, several identical entries → the **most played** (a real tie or no play count → still skipped) | duplicate uploads |

`TOPRESULT` stays the last resort, now step **19**. The rules did not get looser: `version_ok()` and
`artist_ok()` still decide, a slowed video is only ever added as that slowed edit, and a title that does
not match is never accepted for being popular. `MATCHER_VERSION` is now **4**, so songs remembered as
skipped get one more try with the three new steps.

### `--explain`: why was this song skipped?

```bash
export SPOTIFY_COOKIE_FILE=~/cookies/sp_dc.txt
.venv/bin/python -m syncer.app --explain
```

Searches every remembered skip again (read-only - nothing is added, the database is not written) and
prints the parsed title, what `STRICT`/`LOOSE` returned, the query of every step that ran with its top
three results, and a verdict (`MATCH PART` = the song is there and this step finds it now; `still no
match` = Spotify has nothing that fits). The first 25 skips are shown.
`--save-explain` on a normal run stores the rejected results in the database, so `--explain` can show
them later without searching again.

Dates: `2026-11-04`.

## 2026-11-04 (fix + last resort)

### Fixed: the run stopped while building the summary

`UnboundLocalError: cannot access local variable 'summary'` — the extra-step line was added to the summary
before the summary existed. The order is now: counts line → `Matched by extra step:` → `Run stopped:`.

### New step 16: `TOPRESULT` (last resort)

When every other step misses, the **first Spotify result** for the video title is taken - but only when all
three checks pass: the words of the video title really appear in the track title (`same_song_title()`),
the recording is the same version (`version_ok()`), and there is no artist conflict (`artist_ok()`).
It is the last step in the chain, so it can only ever catch songs the other fifteen could not place.
`MATCHER_VERSION` was **3** at that point, so songs remembered as skipped get one more try.

## 2026-11-04 (search steps)

### Fifteen separate extra search steps (and the slowed-version rule)

The three original methods (STRICT, LOOSE, DETAIL) stay exactly as they were. After them, a new module
`syncer/search_steps.py` runs up to **fifteen independent steps**, each one reported by name:

| # | Code | What it does |
|---|---|---|
| 1 | `REVERSED` | artist credit on the right of the dash (`QUERO AMOR - SXYGX x FYU`) |
| 2 | `SINGLE` | collab credit searched one artist at a time |
| 3 | `CHANNEL` | uploader/channel name as the artist |
| 4 | `TOPIC` | `Artist - Topic` channels |
| 5 | `SUFFIX` | cut uploader marketing (`HDN | VIRAL PHONK` → `HDN`) |
| 6 | `COUNTRY` | accents/marks folded (`CORTA NO SALÃO` ↔ `CORTA NO SALAO`) |
| 7 | `FEAT` | featured artist as the main artist |
| 8 | `DURATION` | several versions of one title → choose by video duration |
| 9 | `ARTISTS` | the title searched with every credited artist |
| 10 | `SHORT` | 3-letter titles (`LUZ`) only with a matching artist |
| 11 | `ARTISTLESS` | title-only search |
| 12 | `EXACT` | words without version labels compared exactly |
| 13 | `WORDSET` | same words in another order |
| 14 | `SLOWED` | an explicit `"<song> slowed"` search |
| 15 | `UPLOADER` | uploader name + title in one query |

* **The recording never changes.** Every step accepts a track only when the version agrees: a Slowed video
  is never added as the original, a sped-up edit, a remix, or a different slowed step (Super ↔ Ultra is
  allowed, because uploaders use the two interchangeably).
* **Artist conflicts stop a guess.** When the video credits an artist that the Spotify track does not have,
  the match is refused - so `DESTELLO - HDN` is not added as somebody else's `HDN`.
* **Ambiguity is never resolved by chance:** a step returns a track only when exactly one candidate fits.
* Report: the per-song line carries the matching step (`· SUFFIX ·`), and the summary gets
  `Matched by extra step: SUFFIX ×2, TOPIC ×1`. A miss logs which steps were tried.
* `python -m syncer.app --steps` prints the list; `MATCHER_VERSION` is now **2**, so songs remembered as
  skipped get one more try with the new rules.
* Title parsing also improved: `Song - Artist` order, `x`/`×`/`,`/`&` collabs, `feat.` credits,
  `Artist ~ Song` and `Song || Artists` forms, marketing tags, and the channel as a last-resort artist.
* Tests: **118** (`tests/test_search_steps.py` covers each step, the version rule and the artist conflict).

## 2026-11-04 (newest)

### The playlist name and link are in the report

* One extra read-only YouTube Data API call (`playlists.list?part=snippet`) before the items are read gives
  the playlist **name**, channel and public link. The Spotify playlist has the same name, so that is not
  fetched separately.
* Telegram summary now opens with `Playlist: <name>` + the playlist link; the per-song log header repeats
  it on one line (`Playlist: <name> — <link>`), so an old report is still identifiable.
* The Actions log line is `Playlist: <name> — <link>`, and the Job summary shows `**Playlist:** <name> — <link>`
  (new `python -m syncer.app --playlist-title`, one read-only call, never fails the job).
* A private/renamed/missing playlist now fails with a clear message instead of an empty run.

## 2026-11-04 (latest)

### A song is reported at most twice, then remembered in the database

* **Skips are remembered.** `No confident artist/title/version match`, `Unavailable or missing video title`
  and `Same track already planned in this run` are reported **once**; the video ID is then stored in
  `data/sync-state.json` under `skipped` (title + channel only). Every later run: no Spotify search, no
  Telegram message, no `Skipped` count.
* **Failures are remembered too.** `failures[video_id]` counts failed attempts (`MAX_REPORTED_FAILURES = 2`).
  The first failure is reported with `… (this will be logged once more, then go quiet)`, the second with
  `… (last time logged; retried silently from now on)`. After two failures the song is not retried and not
  reported at all. A successful add clears the counter.
* Two runs a day with 5 unmatched songs therefore produce 5 lines **once**, not 30 lines a day.
* **Manual override wins:** a mapping in `data/track-overrides.json` is honoured even for a remembered
  skip or a retired failure, so the way back is one file edit.
* **Dry runs remember too.** Add results are still never written in a dry run, but the `skipped` /
  `failures` bookkeeping is saved (`save_deferred()`), and the workflow commits it
  (`Update skip/failure bookkeeping (dry run)`). Without this every dry run re-logged the same songs.
* Job summary now shows `Saved songs | Skipped (not retried) | Failed (retried) | Pending`;
  `--db-summary` prints the same table and never lists song titles.
* **`matcher` version in the database.** When the matching rules change, `MATCHER_VERSION` is bumped and
  every remembered skip is cleared once, so a better pattern gets a fair second chance instead of being
  hidden forever.

## 2026-11-04 (later)

### Already-synced songs are database-only

* `Already recorded in the sync database`, `Track already in Spotify playlist` and duplicate videos are
  **neither counted as skips nor reported anywhere**: no Telegram entry, no count line, no summary detail.
  They stay in `data/sync-state.json`, so later runs do not search for them.
* \`Skipped: N\` (and `Skipped: 0`) now counts **only songs with a real reason**: no confident match,
  unavailable video, same track already planned in this run, or a failure.
* The summary keeps a short reason breakdown (`Why songs were skipped: 5 × No confident …`) and the
  per-song lines follow, one line each.

## 2026-11-04

### Telegram: no more message bursts (spam guard)

* One run sends **at most 6 Telegram messages** (`TELEGRAM_MAX_MESSAGES`); whole messages are packed
  together up to the 4000-character limit instead of firing one message per chunk. A 200-song playlist
  now produces ~3 messages (previously 14).
* Beyond the cap, the last message carries `… N more message(s) omitted …` and the full detail stays in
  the Actions log.
* Songs that are **already synced or already in the playlist** are saved to the database but **not
  listed**: only a count line in the summary (`• 125 × Track already in Spotify playlist`).
* Songs that really did not go in (no confident artist/title/version match, unavailable video, any
  failure) are still reported individually with link and reason.
* Per-song entries are one compact line: `#7 ADD: Artist - Song — youtu.be/… · STRICT · open.spotify.com/track/…`.
* If the Telegram send fails (no secrets, blocked bot, rate limit), the same report is printed in the
  Actions log so nothing is lost.

### Matching performance

* Per-run cache for identical Spotify queries (normalised artist + canonical title).
* End-of-run timing line: `Sync finished: 200 video(s) in 812.4s (4.06s each); 431 search request(s),
  37 repeated quer(ies) answered from cache`.

### Schedule and database

* Six runs a day (`0 */4 * * *`); scheduled runs stay dry runs unless `SYNC_ENABLED=true`.
* `--db-summary` prints saved songs per playlist; every run shows the same table in the Job summary.
