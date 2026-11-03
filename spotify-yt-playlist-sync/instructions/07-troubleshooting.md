# 🧯 07 — Troubleshooting (error → හේතුව → විසඳුම)

Log එකේ පේන message එකෙන් හොයාගන්න:

## Setup / configuration

| Message | හේතුව | විසඳුම |
|---|---|---|
| `YOUTUBE_API_KEY is missing` | secret නම වැරදි / නෑ | Settings → Secrets → `YOUTUBE_API_KEY` |
| `Repository secret SPOTIFY_COOKIE is not set` | cookie secret නෑ | [03](03-spotify.md) |
| `No Spotify sp_dc cookie found in Netscape cookie file` | export එකේ `sp_dc` නෑ / JSON format | Netscape **cookies.txt** එකක් export කරන්න |
| `Cannot read Spotify cookie file` | workflow එකේ step 3 fail වුණා | cookie step එකේ log එක බලන්න |
| `Invalid YouTube playlist ID/URL` | link එකේ `list=` නෑ | `…playlist?list=PL…` එකක් දෙන්න |
| `Invalid Spotify playlist ID/URL` | ID එක අකුරු 22ක් නෑ | `open.spotify.com/playlist/<22 chars>` |
| `Invalid configuration or state file I/O error` | `REQUEST_DELAY_SECONDS` / `SPOTIFY_BATCH_SIZE` පරාසයෙන් පිට / state file write කරන්න බෑ | 0–60 සහ 1–100; repo permissions බලන්න |
| `Invalid data/track-overrides.json` | JSON format වැරදි | `{"<11-char video id>": "<22-char track id>"}` |

## YouTube API

| Message | හේතුව | විසඳුම |
|---|---|---|
| `YouTube playlist: GET request failed (HTTP 403)` | quota ඉවර / API enable නෑ / key restrict | Google Cloud → Quotas, API enable, key restriction බලන්න |
| `YouTube playlist: GET request failed (HTTP 404)` | playlist ID වැරදි / private | link එක ආයේ check කරන්න; private නම් public/unlisted කරන්න |
| `YouTube video details returned an invalid response` | API එකේ වෙනසක් | ටිකකින් ආයේ දුවන්න |
| playlist එකේ සින්දු අඩුවෙන් ආවා | playlist එකේ duplicates / private videos | log එකේ `unique video(s)` බලන්න |

## Spotify

| Message | හේතුව | විසඳුම |
|---|---|---|
| `Spotify token request failed (HTTP 400/401)` | cookie expire / revoke වුණා | අලුත් cookies.txt → `SPOTIFY_COOKIE` update |
| `Spotify returned an anonymous session` | cookie එකේ session නෑ | අලුතෙන් login වෙලා export කරන්න |
| `Spotify rejected the available TOTP versions` | community flow එක වෙනස් වුණා | ටිකකින් ආයේ (repo update ඕන වෙන්න පුළුවන්) |
| `Spotify proxied playlist read … (HTTP 401/403)` | token එකට playlist එකට අවසර නෑ / proxy issue | playlist එකේ owner/collaborator ද බලන්න; Free account ද? |
| `HTTP 403` writes වලදී | Spotify playlist edit block කරනවා | test account එකක්; Free account නම් Premium ඕන වෙන්න පුළුවන් |
| `HTTP 429` | rate limit | `REQUEST_DELAY_SECONDS=3` කරන්න; reads auto-retry වෙනවා (3 වතාවක්) |
| `add … outcome unknown` / `UncertainWrite` | timeout / 5xx / GraphQL error | playlist එක අතින් බලන්න → [09](09-recovery-and-maintenance.md) |
| `Spotify batch add size is out of range` | 100ට වඩා / 0 | `SPOTIFY_BATCH_SIZE` 1–100 |

## Telegram

| ලක්ෂණය | හේතුව | විසඳුම |
|---|---|---|
| message එකක් එන්නේ නෑ | bot එකට `/start` දැම්මේ නෑ / chat id වැරදි | [04](04-telegram.md) |
| `Telegram delivery failed (HTTP 400)` | chat id වැරදි | `getUpdates` එකෙන් ආයේ ගන්න |
| `Telegram delivery failed (HTTP 403)` | bot එක group එකෙන් අයින් කරලා | bot එක ආයේ add කරන්න |
| Actions log එකේ විතරයි | secrets නෑ | `TELEGRAM_*` 2 දාන්න (sync එකට බලපෑමක් නෑ) |

## Actions / state

| ලක්ෂණය | හේතුව | විසඳුම |
|---|---|---|
| add වුණා ඒත් `data/sync-state.json` වෙනස් වුණේ නෑ | workflow permissions `Read` | Read and write → [05](05-github-actions.md) |
| `git push` fail (state commit step) | branch protection / permissions | bot එකට push allow කරන්න |
| schedule දුවන්නේ නෑ | default branch එකේ නෑ / disabled | workflow default branch එකට merge කරන්න, Actions enable |
| run එක දිග වැඩි | delay 2s × requests | normal (200 songs ≈ 5–10 min) |
| `Database file is invalid; restore it from Git history` | state JSON කැඩිලා | `git log -- data/sync-state.json` → හොඳ version එක restore |
| එකම සින්දුව ආයේ ආයේ add වෙනවා | state file commit වෙන්නේ නෑ | permissions + pending logic ([09](09-recovery-and-maintenance.md)) |
| `Previous add outcome is uncertain and track was not found` | pending item එක playlist එකේ නෑ | playlist එක බලලා `pending` clear කරන්න ([09](09-recovery-and-maintenance.md)) |

## Debug කරන්න හොඳම ක්‍රමය

1. **Dry run** එකක් දාන්න (`dry_run` ✅) → Telegram full log එකේ හැම සින්දුවකම තීරණය පේනවා
2. වැරදි match එකක් නම් → `data/track-overrides.json` එකට manual mapping
3. Error එකක් නම් → Actions log එකේ step එක + HTTP status එක බලන්න
4. Cookie සම්බන්ධයෙන් සැක නම් → `curl` වලින් debug කරන්න **එපා** (token/cookie leak වෙන්න පුළුවන්)
