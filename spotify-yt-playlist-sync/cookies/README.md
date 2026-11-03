# Spotify cookie

This directory is where a **local** run reads `cookies/spotify.txt` (a Netscape-format cookie export
containing an unexpired `sp_dc` row). The file is **git-ignored** on purpose: a cookie is an account
credential, not a permission-limited API key.

In GitHub Actions the cookie is provided through the repository secret `SPOTIFY_COOKIE`, written to this
path only for the duration of the job and deleted afterwards. Never commit it, never paste it into chat,
issues or logs, and revoke the session (Spotify → sign out everywhere) if it is exposed.

There is no real cookie in this repository.
