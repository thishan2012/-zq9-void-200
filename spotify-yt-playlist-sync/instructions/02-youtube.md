# 🎬 02 — YouTube (source of truth, read-only)

YouTube එකෙන් **කියවනවා විතරයි**. මේ sync එක YouTube එකට කිසිම දෙයක් ලියන්නේ නෑ (like, comment, playlist edit — කිසිවක් නෑ).

## 1. API key එකක් හදන්න

1. <https://console.cloud.google.com/> → project එකක් create/select කරන්න
2. **APIs & Services → Library** → *YouTube Data API v3* → **Enable**
3. **APIs & Services → Credentials → Create credentials → API key**
4. Key එකේ **Edit** → *API restrictions* → **Restrict key** → `YouTube Data API v3` ✅ → Save
   (IP restrictions දාන්න එපා — GitHub runner IPs හැම run එකකදීම වෙනස් වෙනවා)
5. Settings → Secrets and variables → Actions → **`YOUTUBE_API_KEY`** එකට paste කරන්න

## 2. Playlist එක

- **Public** හෝ **Unlisted** playlist එකක් වෙන්න ඕන. Private playlist එකක් API key එකකින් කියවන්න බෑ.
- Link එක: `https://www.youtube.com/playlist?list=PLxxxxxxxxxxxxxxxx`
  ඕනෑම link එකකින් `list=` parameter එක විතරක් ගන්නවා. Playlist ID එක විතරක් දුන්නත් වැඩ කරනවා.
- Secret/Variable එකට දාන්න: **`YOUTUBE_PLAYLIST`**

## 3. Pagination (200 songs = pages 4)

YouTube `playlistItems.list` එකෙන් එක page එකකට **උපරිම 50** දෙනවා. Code එක `nextPageToken` එකෙන් loop කරනවා:

```
page 1 → items 1-50
page 2 → items 51-100
page 3 → items 101-150
page 4 → items 151-200   (nextPageToken නෑ → loop නවතිනවා)
```

Log එකේ පේනවා:
```
INFO YouTube playlist items read: page 1, 50 video(s) so far
…
INFO YouTube playlist loaded: 200 item(s) in 4 page(s), 200 unique video(s)
```

ඊට පස්සේ description + duration ගන්න `videos.list` එක **50 බැගින්** (200 = requests 4). Playlist එකේ එකම video එක දෙපාරක් තිබ්බොත් `unique video(s)` අංකය අඩුවෙන් පෙන්නනවා — දෙවැන්න skip වෙනවා.

## 4. Quota

| Call | Cost | 200 songs |
|---|---|---|
| `playlistItems.list` | 1 unit / page | 4 |
| `videos.list` | 1 unit / batch | 4 |

මුළු **8 units** වගේ — default quota (10,000/day) එකට ගෝල්මුලක් වගේ. දවසට ගොඩක් runs දුවන්නේ නැති නම් ප්‍රශ්නයක් නෑ.

Quota ඉවර වුණොත්: `YouTube playlist: GET request failed (HTTP 403)` → Google Cloud → IAM & Admin → Quotas එකේ බලන්න; පහුවෙනිදා reset වෙනවා.

## 5. Artist එක හඳුනාගන්නේ කොහොමද

පිළිවෙළින්:

1. **Description එකේ credit** — `Artist: Name`, `Name - Song`, හෝ auto-generated `Song · Artist 1 · Artist 2`
2. **`X - Topic` channel** එක → artist = X (`Release - Topic` වගේ generic ඒවා artist කියලා ගන්නේ නෑ)
3. **Title එකේ `Artist - Song`** pattern එක
4. මොකක්වත් හම්බුනේ නෑ → **LOOSE/DETAIL** methods වලින් title එකෙන් විතරක් හොයනවා

`Song - Slowed` වගේ title එකක් `Song` කියන artist එකක් කියලා වරදවා ගන්නේ නෑ (version words වෙන් කරලා බලනවා).

## 6. Playlist එක update කරන විදිය

YouTube playlist එකට අලුත් සින්දු add කරන්න — ඊළඟ run එකේදී ඒවා විතරයි add වෙන්නේ. දැනටමත් sync වුණු ඒවා `data/sync-state.json` එකේ නිසා ආයේ add වෙන්නේ නෑ.

Playlist එකේ ඉඳන් සින්දුවක් අයින් කළොත් **Spotify එකෙන් මකන්නේ නෑ** — මේක one-way sync එකක්.
