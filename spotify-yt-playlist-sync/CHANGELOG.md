# Changelog

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
