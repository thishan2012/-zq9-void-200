# Telegram notifications

1. Create a bot through Telegram's @BotFather and obtain its token.
2. Start a chat with the bot and send it a message. Obtain your chat id with Telegram's `getUpdates` API or
   another trusted method. Treat the token like a password.
3. Set the repository secrets `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
4. Each run sends two kinds of messages:
   * **Summary** — result (`SUCCESS` / `PARTIAL FAILURE` / `FAILED`), counts, and per-song details for
     `SKIP` and `FAIL` only.
   * **Full log** — every song of the run with index, status (`ADD`, `WOULD ADD`, `SKIP`, `FAIL`), channel,
     YouTube link, match method (`MANUAL`/`STRICT`/`LOOSE`/`DETAIL`), Spotify link when known, and the
     reason. This is what you review after a dry run.
5. Messages longer than 4000 UTF-16 units are split on line/song boundaries; very long metadata is
   shortened. Nothing is dropped.
6. Telegram delivery failure is logged in Actions and does not change the sync result. If the secrets are
   absent, both reports go to the Actions log only.
