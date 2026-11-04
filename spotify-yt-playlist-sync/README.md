# YouTube → Spotify playlist sync (phonk edition, experimental)

Experimental **one-way** sync: a public or unlisted **YouTube playlist is the source of truth**, and
tracks are only ever **added** to an existing **Spotify playlist**. Nothing is deleted. Duplicates are
skipped, uncertain matches are skipped instead of guessed, and every decision is reported to Telegram.

Built for large phonk playlists (200+ songs), which is why it batches Spotify writes and stays inside
API rate limits. Spotify cookie login and the web-player token flow are **unofficial** and may stop
working at any time — always test with `--dry-run` first.

---

## What it does, in one run

1. **Read YouTube** with the official Data API: `playlistItems.list` in pages of 50 (`nextPageToken`
   loop, so 200 videos = 4 pages), then `videos.list` in batches of 50 for description + duration.
2. **Get a Spotify token** from your `sp_dc` cookie (TOTP flow, community-maintained version list).
3. **Read the destination playlist** (existing track IDs) — fails closed if this is impossible.
4. **Per video:** manual override → strict match → loose match → detail match → skip.
5. **Skip anything already in the playlist** or already recorded in `data/sync-state.json`.
6. **Batch add** the rest with up to **100 tracks per Spotify request** (2 requests for 200 songs).
7. **Report**: short summary + a **full log of every song** (ADD / WOULD ADD / SKIP / FAIL) to Telegram,
   and the same detail in the Actions log.
8. **Persist** `data/sync-state.json` so the next run never adds the same song twice.

---

## 1. Secrets and variables to set

Go to **Settings → Secrets and variables → Actions** in *your private fork/copy* of this repo.

### Secrets (required)

| Secret | What it is | Where to get it |
|---|---|---|
| `YOUTUBE_API_KEY` | YouTube Data API v3 key (read only) | Google Cloud Console → enable *YouTube Data API v3* → Credentials → API key. Restrict the key to that API. |
| `SPOTIFY_COOKIE` | **Whole Netscape cookies.txt export** of the Spotify account, one single line per cookie, containing at least an unexpired `sp_dc` row | Log in at open.spotify.com → export cookies with a browser extension you trust (format: *Netscape cookies.txt*) |

### Secrets (optional, needed for the Telegram log)

| Secret | What it is |
|---|---|
| `TELEGRAM_BOT_TOKEN` | token from @BotFather |
| `TELEGRAM_CHAT_ID` | your chat id (send the bot a message, then read `getUpdates`) |

### Repository variables (optional overrides)

| Variable | Default | Meaning |
|---|---|---|
| `YOUTUBE_PLAYLIST` | placeholder URL in `sync.yml` | source playlist URL or ID |
| `SPOTIFY_PLAYLIST` | placeholder URL in `sync.yml` | destination playlist URL or ID |
| `REQUEST_DELAY_SECONDS` | `2` | delay before **every** request (0–60). Keep 1–2 for 200-song playlists. |
| `SPOTIFY_BATCH_SIZE` | `100` | tracks per add request (1–100). Lower it if Spotify starts rejecting. |
| `SYNC_ENABLED` | *(unset)* | `true` lets **scheduled** runs write. Unset = scheduled runs stay dry runs. |

> ⚠️ **`SPOTIFY_COOKIE` is an account credential, not an API key.** Anyone who can read it can act as
> that account. Use a disposable account, never commit the cookie file, and if it ever leaks,
> sign out of all devices + change the password on Spotify.
> In the workflow the cookie is written to a git-ignored file and deleted again at the end of the job.

**Where to put your links:** open `.github/workflows/sync.yml` and either edit the two `env` lines
(`YOUTUBE_PLAYLIST` / `SPOTIFY_PLAYLIST`, replacing the `REPLACE_WITH_YOUR_…` placeholders) or — better —
create the two repository variables with the same names. Variables win over the placeholders.

Accepted link formats:

```
https://www.youtube.com/playlist?list=PLxxxxxxxxxxxxxxxx
https://open.spotify.com/playlist/26ADR9K06DZ826IsgTno1S
spotify:playlist:26ADR9K06DZ826IsgTno1S
```

---

## 2. Enable the workflow

1. **Settings → Actions → General → Workflow permissions → Read and write permissions** (the bot commits
   the state file back to the branch).
2. Scheduled workflows only run from the **default branch**, so the workflow, the secrets and the current
   `data/sync-state.json` must all live there.
3. Schedule is `0 */4 * * *` — **six runs a day**, every 4 hours (00/04/08/12/16/20 UTC =
   05:30/09:30/13:30/17:30/21:30/01:30 Sri Lanka). GitHub cron is UTC only and can be delayed.
   Runs with no new songs are quick because already-saved videos are skipped without a search.
4. Manual run: **Actions → YouTube to Spotify sync → Run workflow**, keep **dry_run** checked the first
   time (it is the default), then uncheck it for the real sync. Full detail:
   [instructions/12-dry-run.md](instructions/12-dry-run.md).
5. **Scheduled runs are dry runs by default.** Set the repository variable `SYNC_ENABLED=true` when you
   want the twice-daily schedule to actually add tracks.

For a 200-song playlist expect roughly 5–10 minutes of wall clock (mostly the request delay and the
matching searches), well inside the 180-minute job timeout.

---

## 3. How matching works

| Step | What it searches | Rule |
|---|---|---|
| `MANUAL` | `data/track-overrides.json` | YouTube video ID → Spotify track ID. Bypasses all automatic checks. |
| `STRICT` | `artist + title` | Canonical title equal **and** version signature equal **and** primary artist present. |
| `LOOSE` | full video title | Title similarity ≥ 0.86, versions must still match, close ties are skipped. |
| `DETAIL` | core title (version words removed) | Word order may differ, ≥ 0.86 with matching artist / ≥ 0.93 without, duration within `max(30 s, 25 %)`. |
| `SKIP` | — | No confident match, private/deleted video, already in Spotify, or already recorded. |

`version_signature()` keeps `Slowed`, `Ultra Slowed`, `Super Slowed`, `Sped Up`, `Extended`, `Reverb`,
`8D`, `Nightcore`, `Remix`, `Live`, … apart, so a `(Slowed)` video is never mapped to the original track.
`(Official Video)` / `(Lyrics)` are stripped before comparing.

---

## 4. Duplicate protection

* `data/sync-state.json` records every YouTube video ID → Spotify track ID that was added. The bot
  commits it after each live run, and every run prints a `🗄️ Database` table (saved songs per playlist)
  in its Job summary. Check it locally with `python -m syncer.app --db-summary`.
* Before each add, the destination playlist is read once and every existing track ID is skipped.
* Two videos that resolve to the same track are added only once (the second is reported as a skip).
* Before a batch add, a `pending` record with all tracks of that batch is written. If the HTTP result is
  ambiguous (timeout, 5xx, GraphQL error), the run stops, keeps `pending`, and the next run reconciles
  it: tracks visible in the playlist are recorded, and anything else needs one manual check.
  Writes are **never retried automatically**.
* A failed job mid-batch is safe: the batches that were written are already saved, the pending batch is
  reconciled next run.

---

## 5. Local run

```bash
python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt
# dry run: --dry-run flag or DRY_RUN=true
export YOUTUBE_PLAYLIST='https://www.youtube.com/playlist?list=PL…'
export SPOTIFY_PLAYLIST='https://open.spotify.com/playlist/…'
export YOUTUBE_API_KEY='…'
# optional: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, REQUEST_DELAY_SECONDS, SPOTIFY_BATCH_SIZE
.venv/bin/python -m syncer.app --dry-run     # preview, no Spotify writes
.venv/bin/python -m syncer.app --explain     # why were the skipped songs skipped? (read-only)
.venv/bin/python -m unittest discover -s tests -v   # 139 tests
```

`--explain` searches every remembered skip once more and prints, per song, what `STRICT`/`LOOSE` and each
extra step returned plus a verdict (`MATCH PART` = the song is on Spotify and step `PART` finds it now;
`still no match` = nothing on Spotify fits). Nothing is added and the database is not written; see
[instructions/13-search-steps.md](instructions/13-search-steps.md) §2d.

The cookie file is read from `cookies/spotify.txt` (or `SPOTIFY_COOKIE_FILE`). It is git-ignored.

---

## 6. Telegram output

Two kinds of messages per run, both starting with the **YouTube playlist name and link** (the Spotify
playlist has the same name, so one name is enough — it comes from `playlists.list?part=snippet`):

1. **Summary** — playlist name + link, result, counts, and the skip reasons.
2. **Per-song log** — one line per song that needs attention (`ADD` / `WOULD ADD` / `SKIP` / `FAIL`, with
   YouTube link, match method, Spotify link and reason). Songs that are **already synced, already in the
   playlist or duplicated are saved to the database only**: not counted as skips, not shown anywhere, no
   Spotify search on later runs. `Skipped: N` therefore only counts songs that had a real reason.
3. **At most 6 Telegram messages per run** (`TELEGRAM_MAX_MESSAGES`): whole messages are packed together up
   to the 4000-character limit, so a 200-song playlist produces ~3 messages instead of a dozen. Anything
   beyond the cap is summarised with an "omitted" note and left in the Actions log. If Telegram is not
   configured or the send fails, the same report is printed in the Actions log.
4. **Twenty extra search steps** run after the three matching methods (`REVERSED`, `SINGLE`, `CHANNEL`,
   `TOPIC`, `SUFFIX`, `COUNTRY`, `FEAT`, `DURATION`, `ARTISTS`, `SHORT`, `ARTISTLESS`, `EXACT`, `WORDSET`,
   `SLOWED`, `UPLOADER`, `BROKEN`, `ALBUM`, `PART`, `POPULAR`, and a strictly-checked `TOPRESULT` last resort - see
   [instructions/13-search-steps.md](instructions/13-search-steps.md)). Every
   step keeps the recording identical (a Slowed video is only ever added as that slowed edit) and refuses
   to guess when the artists conflict. Each match is labelled with the step that found it.
5. **A song is reported at most twice.** A skip (`No confident …`, unavailable, same track in the run) is
   logged once and then remembered in `data/sync-state.json` under `skipped`; a failure is logged twice
   (`… logged once more, then go quiet` → `… last time logged`) and remembered under `failures`. From then
   on the song is silent: no Telegram entry, no count, no Spotify search. Delete the entry (or add a
   manual override) to give a song another chance.

Both are also printed to the Actions log.

---

## 7. Files

```
.github/workflows/sync.yml   schedule, dry-run, cookie restore, state commit
syncer/app.py                all logic (YouTube, Spotify transport, matching, batching, reports)
data/sync-state.json         database: per playlist {videos, pending}
data/track-overrides.json    manual YouTube → Spotify mappings
instructions/00…11-*.md      A–Z guides (start at instructions/README.md)
tests/                       65 unit tests (matching, transport, batching, rate limits, reporting)
cookies/README.md            why the cookie file is not in Git
```

## 📚 Docs

**A–Z guides:** [`instructions/README.md`](instructions/README.md) — index එකෙන් පටන් ගන්න.

| # | Guide |
|---|---|
| 00 | [QUICKSTART](instructions/00-QUICKSTART.md) |
| 01 | [Repository secrets / variables (+ "To the one who knows the secrets")](instructions/01-repository-secrets.md) |
| 02 | [YouTube](instructions/02-youtube.md) |
| 03 | [Spotify (cookie, token, rate limit, batch)](instructions/03-spotify.md) |
| 04 | [Telegram (summary + full log)](instructions/04-telegram.md) |
| 05 | [GitHub Actions](instructions/05-github-actions.md) |
| 06 | [How it works (code walkthrough)](instructions/06-how-it-works.md) |
| 07 | [Troubleshooting](instructions/07-troubleshooting.md) |
| 08 | [Security & cookie hygiene](instructions/08-security-and-cookie-hygiene.md) |
| 09 | [Recovery & maintenance](instructions/09-recovery-and-maintenance.md) |
| 10 | [FAQ](instructions/10-faq.md) |
| 11 | [Cheatsheet](instructions/11-cheatsheet.md) |
| 12 | [Dry run (checkbox, env var, schedule switch)](instructions/12-dry-run.md) |
| — | [Secrets template](instructions/secrets-template.md) |

### Secrets at a glance

| Secret | Required | Note |
|---|---|---|
| `YOUTUBE_API_KEY` | ✅ | YouTube Data API v3 |
| `SPOTIFY_COOKIE` | ✅ | whole Netscape cookies.txt (needs `sp_dc`) |
| `YOUTUBE_PLAYLIST` | ✅ (secret **or** variable) | source playlist URL |
| `SPOTIFY_PLAYLIST` | ✅ (secret **or** variable) | destination playlist URL |
| `TELEGRAM_BOT_TOKEN` | optional | full log |
| `TELEGRAM_CHAT_ID` | optional | full log |
| `REQUEST_DELAY_SECONDS` | optional variable | default 2 s |
| `SPOTIFY_BATCH_SIZE` | optional variable | default 100 (1–100) |

Secrets win over variables; both are read (`secrets.X || vars.X || placeholder`).
