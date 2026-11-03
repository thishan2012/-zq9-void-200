# 🗝️ Secrets template — ඔයාගේ එකතුවක් ලියලා තියාගන්න

මේක **copy කරලා ඔයාගේ device එකේ පමණක්** තියාගන්න ෆයිල් එකක්. **repo එකට commit කරන්න එපා**, chat එකට paste කරන්න එපා.
(අගයන් දාන්නේ නැතුව, මොනවද තියෙන්න ඕන කියලා checklist එකක් විදිහට විතරක් පාවිච්චි කරන්නත් පුළුවන්.)

## Checklist

| Secret | තියෙනවද | Last updated | Note |
|---|---|---|---|
| `YOUTUBE_API_KEY` | ☐ | | YouTube Data API v3 only |
| `SPOTIFY_COOKIE` | ☐ | | `sp_dc` row එක තියෙනවද |
| `YOUTUBE_PLAYLIST` | ☐ | | `…?list=PL…` |
| `SPOTIFY_PLAYLIST` | ☐ | | 22-char ID |
| `TELEGRAM_BOT_TOKEN` | ☐ | | @BotFather |
| `TELEGRAM_CHAT_ID` | ☐ | | `/start` දැම්මද |
| `REQUEST_DELAY_SECONDS` *(variable)* | ☐ | | default 2 |
| `SPOTIFY_BATCH_SIZE` *(variable)* | ☐ | | default 100 |

## Fill-in (values **එකතු නොකර** paths/notes විතරයි)

```yaml
repo: thishan2012/<repo-name>
account: <spotify test account email — password manager එකේ තියන්න>

playlists:
  youtube: https://www.youtube.com/playlist?list=________
  spotify: https://open.spotify.com/playlist/______________________

cookie_exported_on: 2026-__-__      # මේ දිනේට මාසයකින් ආයේ බලන්න
cookie_revoked_on:  ________        # leak වුණොත් පුරවන්න

telegram:
  bot: @________bot
  chat_id: ________

notes:
  - run #1 (dry)  වෙලාව: ________  result: ________
  - run #1 (real) වෙලාව: ________  result: ________
```

## Cookie rotate කරන විට

1. අලුත් export එකක් ගන්න
2. `SPOTIFY_COOKIE` secret එක **Update**
3. `cookie_exported_on` අලුත් කරන්න
4. පරණ එක leak වෙලා නම් `cookie_revoked_on` පුරවන්න ([08](08-security-and-cookie-hygiene.md))

> `.gitignore` එකට `secrets-template.local.md` වගේ නමක් add කරන්නත් පුළුවන් — එතකොට ඒක commit වෙන්නේ නෑ.
