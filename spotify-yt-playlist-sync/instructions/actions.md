# Actions, database and troubleshooting

1. Add the secrets and (optionally) the variables listed in the README. Never commit the cookie file.
2. Settings → Actions → General → Workflow permissions: allow **Read and write permissions**, otherwise the
   bot cannot commit `data/sync-state.json`. Branch protection must allow that push.
3. Scheduled workflows run from the **default branch** only, and GitHub UTC cron can be delayed. The
   schedule is `0 0,12 * * *`.
4. Actions → YouTube to Spotify sync → Run workflow: keep **dry_run** checked to preview (no Spotify
   writes, no database changes, but a full Telegram log). Uncheck it to add songs. Nothing is deleted.
5. Variables: `REQUEST_DELAY_SECONDS` (0–60, default 2), `SPOTIFY_BATCH_SIZE` (1–100, default 100),
   `YOUTUBE_PLAYLIST`, `SPOTIFY_PLAYLIST`.

## State and recovery

`data/sync-state.json` maps video IDs to Spotify track IDs per destination playlist. A recorded video is
skipped even if you removed it from Spotify manually — delete its entry to retry it.

Before each batch add, the database stores a `pending` record with every track of that batch. If the
outcome is uncertain (network error, HTTP 5xx, GraphQL error, unreadable body) the run stops and `pending`
stays. On the next run those tracks are reconciled: if they are visible in the playlist they are recorded
and the run continues; if not, the run stops and asks you to check the playlist manually, then clear
`pending` in the state file. Exactly-once behaviour is best effort — do not run several syncs against the
same destination playlist at the same time.

A per-song search error is logged and the run continues; authorization and whole-service errors stop it.
The Telegram report is sent before the database commit step, so also check the overall Actions result.

If setup fails, read the Actions log for the stage and HTTP status: check secret names, API quota,
playlist permissions (`SPOTIFY_PLAYLIST` must be editable by the cookie's account), cookie freshness, and
the unofficial Spotify limitations. Credentials and response bodies are deliberately never logged.
