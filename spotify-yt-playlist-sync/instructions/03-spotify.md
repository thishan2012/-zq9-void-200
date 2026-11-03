# 🟢 03 — Spotify (cookie, token, proxy, rate limit, batch)

මේ කොටස **experimental**: Spotify app credentials පාවිච්චි කරන්නේ නෑ, browser cookie එකකින් login වෙනවා.
Spotify කවදා හරි මේ flow එක වෙනස් කළොත් කැඩෙන්න පුළුවන් — ඒ නිසා **හැම වෙනසකටම කලින් `--dry-run`**.

## 1. Destination playlist එක

- Spotify playlist එකක් (ඔයාගේ account එකේ owner නැත්නම් **collaborator** වෙන්න ඕන)
- Link: `https://open.spotify.com/playlist/26ADR9K06DZ826IsgTno1S`
  (ID එක අකුරු/අංක **22ක්** — නැත්නම් `Invalid Spotify playlist ID/URL`)
- **`SPOTIFY_PLAYLIST`** secret/variable එකට දාන්න
- ⚠️ Spotify **Free** account එකකට playlist edit කරන්න අවසර නොලැබෙන්න පුළුවන් → `HTTP 403`

## 2. Cookie එක (වඩාත්ම වැදගත්)

1. Browser එකේ <https://open.spotify.com> එකට **ඔයාගේ test account එකෙන්** login වෙන්න
2. Cookie export extension එකක් (උදා: "Cookie-Editor" / "Get cookies.txt") → **Netscape cookies.txt** format → export
3. ෆයිල් එකේ මේ වගේ row එකක් තියෙන්න ඕන:

```
.spotify.com	TRUE	/	TRUE	1799999999	sp_dc	AQ...long value...
```

4. ඒ **මුළු ෆයිල් එකේ content එක** (lines ගාණක්) → secret **`SPOTIFY_COOKIE`** එකට paste කරන්න
   - GitHub secrets multi-line support කරනවා
   - `#HttpOnly_` prefix එකත් support කරනවා
   - අනිවාර්යයි: **`sp_dc`** row එකක්, expire නොවුණු එකක්

5. Workflow එක ඒක `cookies/spotify.txt` (git-ignored) එකට ලියලා, job එක ඉවර වෙද්දී **delete** කරනවා.

> ❌ `cookies/spotify.txt` එක repo එකට commit කරන්න **එපා**. `.gitignore` එකේ දාලා තියෙනවා — ඒත් ඒක force-add කරන්න එපා.

## 3. Token flow (code එක ඇතුළේ)

```
sp_dc cookie
   ↓ TOTP code (community-maintained version list)
https://open.spotify.com/api/token?reason=transport&productType=web-player&totp=…
   ↓ accessToken (≈1h)
api.spotify.com  /  api-partner.spotify.com
```

- Token එක **cookie එක නෙවෙයි** — expire වෙනවා. ඒත් token එකෙන් playlist edit කරන්න පුළුවන්.
- Token request එකේදී 400 ආවොත් code එක පරණ TOTP versions 3ක් උත්සාහ කරනවා.
- Anonymous session එකක් ආවොත් (`isAnonymous`) → `export a fresh cookie`.

## 4. Backend දෙකක් (proxy)

1. **REST** — `api.spotify.com/v1/...`, `https://corsly-proxy2.camdvr.org/` proxy හරහා
2. **Web-player GraphQL** — `api-partner.spotify.com/pathfinder/v2/query`

Read එකේදී විතරයි fallback: REST read 401/403/404/405/429/501 → web-player; proxy fail → direct web-player.
**Writes එකක් කවදාවත් retry නෑ** (add එක දැනටමත් වෙලා තියෙන්න පුළුවන් නිසා).

⚠️ Proxy එකට **bearer token** එක යනවා → proxy operator එකට විශ්වාස කරන්න ඕන. Token එක expire වෙන නිසා cookie එක තරම් අවදානමක් නෑ.

## 5. Rate limit ✅

| Setting | Default | මොකද |
|---|---|---|
| `REQUEST_DELAY_SECONDS` | `2` | හැම request එකට කලින් නිදාගන්නවා. 200 search = ~6.5 min. |
| Retry | 429/5xx → `Retry-After` අනුව 3 වතාවක් (reads විතරයි) | backoff: 5s → 10s → 20s, cap 60s |

Search 200ක් එක පාර දැම්මොත් Spotify block කරනවා → ඒ නිසා delay එක **අඩු කරන්න එපා**. Playlist එක ලොකු නම් 2s තියාගන්න; නැත්නම් 1s。
1–2 seconds තමයි sweet spot.

## 6. Batch add ✅ (200 songs = requests 2)

Spotify එකේ එක add request එකකට **උපරිම URIs 100**:

```
200 songs → [100 tracks] + [100 tracks] → requests 2
```

| Setting | Default | පරාසය |
|---|---|---|
| `SPOTIFY_BATCH_SIZE` | `100` | 1–100 (100ට වඩා දුන්නොත් 100ට clamp වෙනවා) |

**වැදගත්:** `SPOTIFY_BATCH_SIZE` කියන්නේ **එක HTTP request එකකට tracks කීයද** කියන එක විතරයි.
Batch එකක් fail වුණොත් (උදා: HTTP 400) ඒ batch එකේ tracks **FAIL** වෙලා log වෙනවා; ඊළඟ run එකේ ආයේ උත්සාහ කරනවා (state එකේ record වෙලා නොතිබෙන නිසා). Spotify සමහර වෙලාවට විශාල batch reject කරනවා නම් `50` කරන්න.
Batch එකක ප්‍රතිඵලය **අපැහැදිලි** නම් (timeout / 5xx / GraphQL error) → run එක නවතිනවා, `pending` state එකේ තියෙනවා, ඊළඟ run එකේ reconcile වෙනවා (duplicate නෑ).

## 7. Cookie expire වුණොත්

ලක්ෂණ: `Spotify token request failed (HTTP 400/401)` හෝ `Spotify returned an anonymous session`.

කරන්න: අලුත් cookies.txt export එකක් ගෙන `SPOTIFY_COOKIE` secret එක **update** කරන්න. (Spotify එකේ "logout everywhere" කළොත්ත් cookie එක invalid වෙනවා.)
