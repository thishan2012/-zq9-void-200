# 📨 04 — Telegram (summary + full log)

## 1. Bot එකක් හදන්න

1. Telegram එකේ **@BotFather** → `/newbot` → නමක් + username (`…bot` අන්ත වෙන්න ඕන)
2. Token එක එනවා: `123456789:AAH…` → **`TELEGRAM_BOT_TOKEN`** secret එකට දාන්න
3. ඔයාගේ bot එකට **`/start`** එවන්න (bot එකට ඔයාට message එවන්න බෑ, ඔයා chat එකක් පටන් ගත්තොත් විතරයි)

## 2. Chat ID එක ගන්න

Browser එකේ මේ URL එක open කරන්න (token එක ඔයාගේ එක දාන්න):

```
https://api.telegram.org/bot<TOKEN>/getUpdates
```

Response එකේ `"chat":{"id":123456789, …}` → ඒ අංකය **`TELEGRAM_CHAT_ID`**.

- Group/Channel එකකට යවන්න ඕන නම් id එක **negative** අංකයක් (`-100…`) වෙනවා, ඒ නිසා bot එක ඒ group එකට **admin/member** කරන්න.
- `getUpdates` එකේ `[]` පෙන්නනවා නම්: bot එකට අලුතෙන් message එකක් එවලා ආයේ try කරන්න.

## 3. ඔයාට එන messages (එක run එකකට 2ක් + splits)

### මොනවද **ලොක් එකට එන්නේ නැත්තේ** (2026-11 update)

දැනටමත් sync වෙලා තියෙන / playlist එකේ තියෙන සින්දු **Telegram එකට යන්නේ නෑ** — ඒවා database එකේ save කරනවා විතරයි:
`Already recorded in the sync database`, `Track already in Spotify playlist`, `Duplicate video in the YouTube playlist`.
ඒවා ගණන header එකේ එක පේළියකින් පෙන්නනවා:

```
YouTube → Spotify log (DRY RUN): 36 song(s) to report
Already present, not listed (125): 118 × Track already in Spotify playlist; 7 × Already recorded in the sync database
```

ඒ නිසා 200-song playlist එකක මැසේජ් 14ක් වෙනුවට **2–4ක්** විතරයි එන්නේ.
(මේවා Actions log එකේ `SKIP … already recorded` විදිහට තවම තියෙනවා, Job summary එකේ counts වලත් පේනවා.)

**1) Summary**
```
YouTube → Spotify SYNC: SUCCESS
Added: 187 | Skipped: 12 | Failed: 1

SKIP: Artist - Some Song
Channel: Uploader
YouTube: https://www.youtube.com/watch?v=…
Reason: Track already in Spotify playlist
…
```
→ මේකේ තියෙන්නේ **SKIP + FAIL විස්තර විතරයි** (+ counts).

**2) Full log** (ඔයා ඉල්ලපු එක 🌚)
```
YouTube → Spotify full log (SYNC): 200 event(s)

#1 ADD: Artist - Song
Channel: Uploader
YouTube: https://www.youtube.com/watch?v=…
Match: STRICT
Spotify: https://open.spotify.com/track/…
Reason: Added to Spotify

#2 SKIP: …
```

හැම සින්දුවකටම: index, status (`ADD` / `WOULD ADD` / `SKIP` / `FAIL`), channel, YouTube link, match method
(`MANUAL` / `STRICT` / `LOOSE` / `DETAIL`), Spotify link (දන්නවා නම්), reason.

- 4000 UTF-16 units ට වැඩි නම් message එක **line boundary එකෙන්** split වෙනවා — entry එකක් මැදින් කැපෙන්නේ නෑ
- 200 songs ≈ messages 3–5ක් (summary එකුත් එකතුව)
- Dry run එකේදී `WOULD ADD` කියලා එනවා

## 4. Secrets නැති නම්

Telegram configure නොකළොත් summary + full log **Actions log** එකේ විතරයි (`telegram not configured; summary only in Actions log`).
Sync එකට කිසිම බලපෑමක් නෑ.

## 5. Privacy

- Action log එකේ **secrets, tokens, HTTP bodies print වෙන්නේ නෑ**.
- Telegram එකට යන්නේ **public metadata** විතරයි: video title, channel, links, reply reason. Cookie/token කවදාවත් යන්නේ නෑ.
- Bot token එක තියෙන කෙනාට ඔයාගේ chat එකට message එවන්න පුළුවන් → token එක password එකක් වගේ තියාගන්න.
