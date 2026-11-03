# 🚀 00 — QUICKSTART (විනාඩි 15)

## 0. ඔයාට ඕන දේවල්

- Spotify account එකක් (disposable/test එකක් හොඳයි) + edit කරන්න පුළුවන් playlist එකක්
- Google Cloud account එකක් (YouTube API key එකකට)
- Telegram (optional — නමුත් full log එකට ඕන)
- මේ repo එකේ **ඔයාගේ copy** එකක් (private හෝ public — cookie එක repo එකට යන්නේ නෑ)

## 1. Secrets 5ක් + 1ක් (කෙටියෙන්)

Repo → **Settings → Secrets and variables → Actions**

**Secrets** tab එකේ "New repository secret":

| Name | Value |
|---|---|
| `YOUTUBE_API_KEY` | Google Cloud → API key ([02](02-youtube.md)) |
| `SPOTIFY_COOKIE` | Netscape cookies.txt export එකේ **මුළු content එක** ([03](03-spotify.md)) |
| `YOUTUBE_PLAYLIST` | `https://www.youtube.com/playlist?list=PL…` |
| `SPOTIFY_PLAYLIST` | `https://open.spotify.com/playlist/…` |
| `TELEGRAM_BOT_TOKEN` | @BotFather token ([04](04-telegram.md)) |
| `TELEGRAM_CHAT_ID` | ඔයාගේ chat id ([04](04-telegram.md)) |

මේ 6ම **Secrets** tab එකේම දාන්න පුළුවන් (කිසි ප්‍රශ්නයක් නෑ — workflow එක `secrets.* || vars.*` දෙකම කියවනවා).
විස්තර + "To the one who knows the secrets" → [`01-repository-secrets.md`](01-repository-secrets.md)

## 2. Actions permissions

**Settings → Actions → General → Workflow permissions → Read and write permissions** → Save.

## 3. Playlist link දෙක check කරන්න

`sync.yml` එකේ placeholders තියෙනවා නම්, ඔයාගේ `YOUTUBE_PLAYLIST` / `SPOTIFY_PLAYLIST` secrets ඒවා override කරනවා.
Link format එක වැරදි නම් run එක මුලින්ම `Invalid … playlist ID/URL` කියලා නවතිනවා.

## 4. පළමු run එක (dry run)

**Actions → YouTube to Spotify sync → Run workflow**
- Branch: default branch
- `dry_run`: ✅ **checked**

Run එක ඉවර වෙද්දී Telegram එකට messages දෙකක් එනවා: **Summary** + **Full log**.
Log එකේ `STRICT / LOOSE / DETAIL / SKIP` බලන්න. වැරදි match එකක් තියෙනවා නම් `data/track-overrides.json` එකට manual mapping දාන්න.

## 5. ඇත්තටම sync කරන්න

`dry_run` ❌ uncheck → Run workflow. දැන් `data/sync-state.json` commit වෙනවා (bot එකෙන්).

## 6. පස්සේ

- දවසට දෙපාරක් ඔටෝ: `0 0,12 * * *` UTC = **05:30 / 17:30** (Sri Lanka)
- Error එකක්: [`07-troubleshooting.md`](07-troubleshooting.md)
- Cookie expire: [`09-recovery-and-maintenance.md`](09-recovery-and-maintenance.md)

---

## පොදු වැරදි 4ක්

1. **`SPOTIFY_COOKIE` එකේ `sp_dc` නෑ** → `No Spotify sp_dc cookie found` — export එක අලුත් කරන්න.
2. **Destination playlist එක ඒ account එකට edit කරන්න බෑ** → `HTTP 401/403` — playlist එකේ owner/collaborator ද බලන්න.
3. **Secret එකේ නම වැරදියි** → `YOUTUBE_API_KEY is missing`.
4. **Workflow permissions "Read" විතරයි** → state commit fail වෙනවා (playlist එකට add වෙලා තිබ්බත්).
