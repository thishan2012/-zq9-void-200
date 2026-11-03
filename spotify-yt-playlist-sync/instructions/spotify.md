# Spotify setup (experimental)

1. The destination playlist URL is configured in `.github/workflows/sync.yml` (`SPOTIFY_PLAYLIST`) or with
   the repository variable of the same name. Your Spotify account must be allowed to edit that playlist
   (owner or collaborator). Spotify Free accounts may be refused — that shows up as HTTP 401/403.
2. While logged in to the test account at open.spotify.com, export its cookies in **Netscape cookies.txt
   format** with a browser tool you trust.
3. Put the **whole export** into the repository **secret** `SPOTIFY_COOKIE` (multi-line secrets are fine;
   the workflow writes them to a git-ignored file for the job and deletes it afterwards). The export needs
   an unexpired `sp_dc` cookie for `spotify.com`; the `#HttpOnly_` prefix is supported.
4. Never commit the cookie file, never paste it into chat/issues/logs. Rotate it when it expires by
   replacing the secret.

**Risk:** a cookie is not a permission-limited API key — anyone who reads it can act as that account. Use
a disposable test account. If it leaks: Spotify → *Sign out everywhere* + password change, then issue a
new cookie.

The token exchange uses a community-maintained TOTP version list from GitHub; Spotify can change this at
any time. Search, playlist reads and adds via web-player tokens are unofficial and may be refused.
HTTP 401/403 stops the run instead of pretending songs were synced. No Spotify app credentials are used.

## Proxy and web-player backend

The sync first tries the Web API through `https://corsly-proxy2.camdvr.org/`, and falls back to the web
player's Pathfinder API if a playlist **read** returns 401, 403, 404, 405, 429 or 501. Only reads fall
back; the backend that successfully reads is the one used for writes, and a write is never retried.

The proxy receives the **Spotify bearer access token** in the Authorization header. Only use it if you
trust its operator and logging. Redirects are never followed when credentials are forwarded, and only
`api.spotify.com` / `api-partner.spotify.com` may be sent through it. YouTube and Telegram requests never
use it.

## Rate limits and batching

* `REQUEST_DELAY_SECONDS` (default 2) is applied before every request; for a 200-song playlist keep it at
  1–2 s. This is what keeps 200 searches from tripping Spotify's rate limiter.
* Read requests are retried after HTTP 429/5xx, honouring `Retry-After` (up to 3 attempts, exponential
  backoff capped at 60 s). Writes are **never** retried.
* Adds are sent in batches: `SPOTIFY_BATCH_SIZE` (default and maximum **100**), so 200 songs = 2 requests.
  A batch that is rejected outright is reported and retried on the next run; a batch with an ambiguous
  result stops the run with a `pending` record.
