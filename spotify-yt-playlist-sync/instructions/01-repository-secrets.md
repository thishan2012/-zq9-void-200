# 🔐 01 — Repository Secrets / Variables (To the one who knows the secrets)

මේක තමයි සම්පූර්ණ ලැයිස්තුව. ඔයාගේ screenshot එකේ 6ම **Secrets** tab එකේ තියෙනවා — ඒක **හරි** ✅.
Variables tab එකට යවන්න ඕන දේවල් තියෙනවා නම් ඒවා පහළ "optional" කොටසේ.

## A. අනිවාර්ය secrets (2)

| Name | අගය | නැති නම් |
|---|---|---|
| `YOUTUBE_API_KEY` | YouTube Data API v3 key | `YOUTUBE_API_KEY is missing` → run fail |
| `SPOTIFY_COOKIE` | Netscape cookies.txt export එකේ **සම්පූර්ණ content** | `Repository secret SPOTIFY_COOKIE is not set` → run fail |

## B. Playlist links (2) — Secrets හෝ Variables

| Name | අගය | තැන |
|---|---|---|
| `YOUTUBE_PLAYLIST` | `https://www.youtube.com/playlist?list=PL…` | Secrets ✅ හෝ Variables ✅ |
| `SPOTIFY_PLAYLIST` | `https://open.spotify.com/playlist/…` | Secrets ✅ හෝ Variables ✅ |

මේවා secret එකක් නෙවෙයි — playlist link public එකක්. ඒත් **Secrets tab එකේ දාලා තියෙන එක වැරදි නෑ**; workflow එක මෙහෙම කියවනවා:

```yaml
YOUTUBE_PLAYLIST: ${{ secrets.YOUTUBE_PLAYLIST || vars.YOUTUBE_PLAYLIST || 'https://www.youtube.com/playlist?list=REPLACE_…' }}
SPOTIFY_PLAYLIST: ${{ secrets.SPOTIFY_PLAYLIST || vars.SPOTIFY_PLAYLIST || 'https://open.spotify.com/playlist/REPLACE_…' }}
```

> ⚠️ එකම නමින් **Secrets සහ Variables දෙකේම** තියෙනවා නම් → **Secrets එක දිනනවා**. ඒ නිසා වෙනස් කරන වෙලාවට බලන්න ඔයා edit කරන්නේ මොකක්ද කියලා.

## C. Telegram (2) — optional, නමුත් full log එකට ඕන

| Name | අගය | නැති නම් |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | @BotFather එකෙන් | log එක Actions වලට විතරයි |
| `TELEGRAM_CHAT_ID` | ඔයාගේ chat id (negative group id එකකුත් වෙන්න පුළුවන්) | ඒ වගේම |

## D. Optional tuning (Variables තැනට හොඳයි)

| Name | Default | මොකද |
|---|---|---|
| `REQUEST_DELAY_SECONDS` | `2` | හැම request එකට කලින් delay (0–60). Rate limit වලට |
| `SPOTIFY_BATCH_SIZE` | `100` | එක add request එකකට tracks (1–100) |
| `SYNC_ENABLED` | *(unset)* | `true` = scheduled runs (දවසට 4) ඇත්තටම write කරයි; unset = dry run |

මේවා **secret එකක් නෙවෙයි** — Variables tab එකට දාන්න:
**Settings → Secrets and variables → Actions → Variables → New repository variable**

> ⚠️ `SPOTIFY_BATCH_SIZE=100` කියලා **secret** එකක් විදිහට දැම්මොත් ඒක වැඩ කරන්නේ නෑ (workflow එක `vars.` වලින් කියවන නිසා).
> දැම්මා නම් අයින් කරලා variable එකක් විදිහට දාන්න — නැත්නම් default 100 දිගටම වැඩ කරනවා (ප්‍රශ්නයක් නෑ).

---

## ඔයාගේ ලැයිස්තුව check කරමු

| ඔයා තියෙනවා කිව්ව | තත්වය | කරන්න ඕන |
|---|---|---|
| `SPOTIFY_COOKIE` | ✅ හරි | ඒකේ `sp_dc` row එක තියෙනවද බලන්න (03) |
| `SPOTIFY_PLAYLIST` | ✅ හරි | link format එක බලන්න |
| `TELEGRAM_BOT_TOKEN` | ✅ හරි | bot එකට `/start` දැම්මද? |
| `TELEGRAM_CHAT_ID` | ✅ හරි | 04 එකේ විදියට confirm කරන්න |
| `YOUTUBE_API_KEY` | ✅ හරි | YouTube Data API v3 enable ද? |
| `YOUTUBE_PLAYLIST` | ✅ හරි | public/unlisted ද? |

**ඉතිරි: `REQUEST_DELAY_SECONDS` (optional) + `SPOTIFY_BATCH_SIZE` (optional, variable එකක් විදිහට).**
මේ 2 නැතුවත් run එක වැඩ කරනවා — defaults: 2s delay, 100 batch size.

## "To the one who knows the secrets" — secrets වලට treat කරන්න ඕන විදිය

මේ 4 රීතිය මතක තියාගන්න:

1. **Cookie/keys කියන්නේ අංක නෙවෙයි, යතුරු.** `SPOTIFY_COOKIE` = account එකට login වෙන්න පුළුවන් credential එකක්. `YOUTUBE_API_KEY` = ඔයාගේ quota.
2. **එකම තැනක තියන්න.** Secrets tab එකේ තියන්න. Chat, issue, commit, screenshot, log එකට දාන්න එපා. (Arena එකේ chat එකටවත් paste කරන්න එපා 😅)
3. **ඔයාට පේන තැනකට එනවා නම් revoke කරන්න.** Spotify → Sign out everywhere ([08](08-security-and-cookie-hygiene.md)).
4. **හැම secret එකකටම "අවම අවසරය".** YouTube key එක YouTube Data API v3 එකට විතරක් restrict කරන්න; Spotify එකට **disposable account** එකක්.

## Secret එකක් update කරන විදිය

1. Settings → Secrets and variables → Actions → secret එකේ නම click
2. **Update** → අලුත් අගය → **Update secret**
3. ඊළඟ run එකේදී අලුත් අගය පාවිච්චි වෙනවා (එකම run එකේ නෑ)

## Secret එකක් delete කරන විදිය

Secret එකේ නම click → **Delete**. Delete කළාම workflow එක ඒ අගය නැතුව යනවා → `… is missing` error.

> repo එකේ තියෙන `.github/workflows/sync.yml` එකේ **කිසිම secret එකක අගයක් ලියලා නෑ** — නම් විතරයි. ඒ නිසා repo එක public වුණත් secret අගයන් පේන්නේ නෑ.
