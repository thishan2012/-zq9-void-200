# Changelog

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
