# 🔒 08 — Security (cookie hygiene) — අනිවාර්යයි

## 1. Cookie එක කියන්නේ මොකක්ද

`sp_dc` cookie එක = ඔයාගේ Spotify account එකේ **session credential** එකක්. API key එකක් වගේ "අවසර සීමා කරපු" දෙයක් නෙවෙයි.
ඒක තියෙන කෙනාට ඔයාගේ account එකෙන් playlist edit කරන්න, library එක බලන්න පුළුවන් (playlist add එකට විතරක් සීමා වෙන්නේ නෑ).

ඒ නිසා:

| ✅ කරන්න | ❌ කරන්න එපා |
|---|---|
| GitHub **secret** එකක තියන්න | repo එකට commit කරන්න (`cookies/spotify.txt`) |
| **disposable/test account** එකක් පාවිච්චි කරන්න | main account එකේ cookie එක දෙන්න |
| expire වුණාම update කරන්න | chat / issue / screenshot / log එකට paste කරන්න |
| leak වුණොත් revoke කරන්න | අලුත් cookie එකක් ගත්තට පරණ එක තියන්න |

## 2. මේ repo එකේ කරලා තියෙන දේ

- `cookies/spotify.txt` **`.gitignore`** එකේ (repo එකේ කවදාවත් තියෙන්නේ නෑ)
- Workflow එකේ cookie එක `secrets.SPOTIFY_COOKIE` එකෙන් ලියලා, **job එක ඉවර වෙද්දී `rm -f`** කරනවා
- Logs වලට cookie/token/response body print වෙන්නේ නෑ (`Client.request` එකේ හිතාමතාම sanitize කරලා)
- HTTP redirects follow කරන්නේ නෑ (proxy එකට bearer token එක වෙන host එකකට යන්න බෑ)

## 3. Cookie එක leak වුණොත් (හෝ බය නම්) — 3 විනාඩියේ

1. <https://www.spotify.com/account/security/> → **Sign out everywhere**
2. Password එක change කරන්න
3. Connected apps check කරන්න → හඳුනාගන්න බැරි app එකක් තියෙනවා නම් remove
4. අලුත් cookie එකක් export කරලා `SPOTIFY_COOKIE` secret එක update කරන්න
5. පරණ cookie එක **revoke වුණා නම්** (session invalid) ඒක තවත් වැඩ කරන්නේ නෑ ✅

## 4. Git history එකේ cookie එකක් තියෙනවා නම්

Git history එකේ තියෙන ෆයිල් එකක් delete කළාට **blob එක ඉතුරු වෙනවා**. ඒ නිසා:

1. ඉස්සෙල්ලා **revoke** කරන්න (ඒක තමයි ඇත්තම විසඳුම)
2. History rewrite කරන්න ඕන නම් (force push):

```bash
# git-filter-repo (recommended)
pip install git-filter-repo
git filter-repo --path cookies/spotify.txt --invert-paths
git push --force origin main
```

`filter-repo` නැති නම් `git filter-branch --index-filter 'git rm --cached --ignore-unmatch cookies/spotify.txt' HEAD`

⚠️ Force push කළාම forks/clones තියෙන අයට impact වෙනවා; GitHub cached views හෝ forks වල පරණ blob එක ටික කලක් තියෙන්න පුළුවන් — ඒ නිසා revoke එක **අනිවාර්යයි**.

## 5. Python script එක ඇතුළේ (code-level) safety

| Safety | තැන |
|---|---|
| `umask 077` + delete after job | `.github/workflows/sync.yml` |
| `#HttpOnly_` prefix handling | `sp_dc_from_file()` |
| Domain check (`spotify.com` විතරයි) | `sp_dc_from_file()` |
| Proxy target whitelist | `Client.request()` |
| No redirects on proxied requests | `Client.request()` |
| No retries on writes | `Client.request()` + `flush_batch()` |
| Sanitized log text | `log_text()` / `issue_text()` |

## 6. අනිත් secrets

| Secret | Leak වුණොත් |
|---|---|
| `YOUTUBE_API_KEY` | ඔයාගේ quota use වෙනවා → Google Cloud → delete + අලුත් key |
| `TELEGRAM_BOT_TOKEN` | අනිත් අයට ඔයාගේ bot එකෙන් message එවන්න පුළුවන් → @BotFather → `/revoke` |
| `TELEGRAM_CHAT_ID` | ඒ තරම් අවදානමක් නෑ (ඒත් bot token එක්ක එකතුව අවදානම්) |

## 7. Proxy එක ගැන

`corsly-proxy2.camdvr.org` කියන්නේ තුන්වෙනි පාර්ශ්වයක් — ඒකට **bearer token** එක යනවා (cookie එක නෙවෙයි).
Token එක 1h වගේ expire වෙනවා, ඒත් ඒ කාලය ඇතුළේ playlist edit කරන්න පුළුවන්. Proxy operator එකට විශ්වාස කරන්න බැරි නම් මේ project එක පාවිච්චි කරන්න එපා.
