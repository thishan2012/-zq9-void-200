# Actions, database and troubleshooting

1. Add the secrets described in the other guides and commit the Spotify cookie file on the branch running the workflow. Keep the repo private.
2. Under Settings → Actions → General → Workflow permissions, allow **Read and write permissions**. Branch protection may prevent the bot from pushing: permit its update or arrange another persistence method. A failed database push fails the workflow; resolve it before relying on another run. The code checks existing Spotify tracks to reduce duplicates, but cannot guarantee exactly-once behavior under concurrent external edits or service failures.
3. GitHub scheduled workflows run from the **default branch**, so the workflow, cookie and current database need to be on that branch. This project's initial schedule is `0 0,12 * * *` (00:00 and 12:00 UTC; 05:30 and 17:30 Sri Lanka time). Edit the cron to change it. GitHub can delay scheduled jobs and may disable schedules after long repository inactivity.
4. Actions → YouTube to Spotify sync → Run workflow: choose the branch and leave **dry_run** checked to preview. Uncheck it to add songs. Dry run reads services and sends Telegram but writes neither Spotify nor the database. Check the logs for individual ADD / SKIP / FAIL entries. No song is deleted.
5. Optional: set Actions repository variable `REQUEST_DELAY_SECONDS` from 0 to 60 (default 2). Delay occurs before most HTTP requests. For a large playlist, ensure the job timeout is sufficient.

## State and recovery

`data/sync-state.json` maps video IDs to Spotify track IDs per destination playlist. A video already recorded is skipped even if manually removed from Spotify. To retry one, remove its entry manually. Tracks already in the destination are also skipped. Matches without a reliable artist/title are skipped and retried in later runs. A per-song search/add error is logged and processing continues; authorization and whole-service errors stop the run. A Telegram summary can be sent before the database commit step, so check the overall Actions result too.

Before an add request, the database records a pending operation. If its outcome is uncertain (e.g. network timeout), the run stops. On the next run the program reconciles it if that track is visible in the playlist. If it is not visible, manually inspect the playlist and clear `pending` in the state file only after deciding it is safe to retry. Never run multiple sync jobs on different branches against the same destination at the same time. Concurrency is serialized per branch, not across branches or outside GitHub.

If setup fails, inspect Actions logs for which stage and HTTP status failed. Check secret names, API quota, playlist permissions, Spotify cookie freshness and the unofficial Spotify endpoint limitations. Credentials and HTTP response bodies are deliberately not logged. If Spotify forbids web-player-token operations, this experimental approach cannot bypass that restriction.
