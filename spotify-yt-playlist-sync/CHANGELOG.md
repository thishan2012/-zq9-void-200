# Changelog

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
