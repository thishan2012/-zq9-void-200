# YouTube → Spotify playlist sync (testing)

Experimental one-way sync from a **public or unlisted YouTube playlist** to an **existing Spotify playlist**. It searches by artist and title, skips uncertain matches and existing tracks, and records successful mappings in a JSON database. It never deletes tracks from Spotify. Runs twice daily via GitHub Actions or manually in dry-run mode, with a Telegram summary.

**Experimental:** Spotify cookie login and the use of its web-player token with playlist/search endpoints are unofficial and may stop working or reject writes (including HTTP 403). Spotify API requests first use the configured user-provided proxy and may fall back to unofficial web-player operations; see the Spotify setup guide for token exposure and proxy requirements. Neither successful authentication nor Spotify Free compatibility is guaranteed. Test with a dedicated account and use dry run first. The sync cannot be verified against your account until you provide your own configuration.

## Setup

1. [YouTube API and playlist](instructions/youtube.md)
2. [Spotify cookie and destination playlist](instructions/spotify.md)
3. [Telegram bot](instructions/telegram.md)
4. [GitHub Actions, schedules, dry run and troubleshooting](instructions/actions.md)

Required repository **secret**: `YOUTUBE_API_KEY`. For Telegram summaries also set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`. The two playlist URLs are configured directly in `.github/workflows/sync.yml`; change them there if needed. The Spotify cookie is read from `cookies/spotify.txt`, deliberately stored in this private repository as requested; **it is an account credential, not a permission-limited API key**. Never add it to a public repo or share it. Any repo reader and workflow with access can use it; old copies remain in Git history after replacement. See the Spotify instructions.

The database is `data/sync-state.json`; a workflow commit persists it even if a later song fails. GitHub Actions needs permission to write to the branch. Schedules run only on the default branch; configuration and cookie must be available there. Runs can be delayed by GitHub.

## Local preview

Python 3.11+: `pip install -r requirements.txt`. Set `YOUTUBE_PLAYLIST`, `SPOTIFY_PLAYLIST`, `YOUTUBE_API_KEY` and optionally the Telegram variables in your environment (see instructions), place the cookie file, then run `python -m syncer.app --dry-run`. The playlist values in the workflow are not automatically used for local runs. Omit `--dry-run` to perform the sync. You can set `REQUEST_DELAY_SECONDS` (default 2, range 0–60) and `SPOTIFY_COOKIE_FILE` (default `cookies/spotify.txt`). Do not print secrets or export them into shell history.

Tests: `python -m unittest discover -s tests -v`.
