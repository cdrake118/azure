# One-tap voicemail upload from iPhone (Apple Shortcut)

This sets up a Shortcut so you can log a voicemail straight from the iPhone
**Share** menu: tap a voicemail → Share → your shortcut → type the caller's
number → it uploads the audio and creates a logged incident.

## 1. Set an upload token (recommended)

So the Shortcut can authenticate with just a URL, set an upload token as a
Railway service variable (or local env var):

```
ROBOCALL_UPLOAD_TOKEN=<a long random string>
```

Generate one with: `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`

If you skip this, the Shortcut must instead send an `Authorization: Basic …`
header built from your `ROBOCALL_USERNAME`/`ROBOCALL_PASSWORD` — doable, but the
token is much simpler.

## 2. Build the Shortcut

Open the **Shortcuts** app → **+** (new shortcut) → name it e.g. *Log Voicemail*.

1. **Settings (ⓘ at the bottom, or the info icon):**
   - Turn on **Show in Share Sheet**.
   - Under **Share Sheet Types**, accept **Media** and **Files** (turn the
     others off if you like).

2. **Add action → "Ask for Input":**
   - Input Type: **Text**
   - Prompt: `Caller's phone number`
   - (This is the number that left the voicemail.)

3. **Add action → "Get Contents of URL":**
   - **URL:**
     `https://YOUR-APP.up.railway.app/api/voicemails?token=YOUR_UPLOAD_TOKEN`
   - Tap **Show More**.
   - **Method:** `POST`
   - **Request Body:** `Form`
   - Add these form fields:
     | Key | Type | Value |
     | --- | --- | --- |
     | `file` | File | **Shortcut Input** |
     | `from_number` | Text | **Provided Input** (the "Ask for Input" result) |

   To pick **Shortcut Input** / **Provided Input** as a field value, tap the
   value box and choose the variable from the suggestions bar.

That's it — save the shortcut.

## 3. Use it

On your iPhone: **Phone app → Voicemails → tap a voicemail → Share icon →
Log Voicemail → type the caller's number → Done.**

The voicemail appears on your dashboard with an inline audio player, logged as a
`voicemail` contact from that number.

## Notes

- **File format:** iPhone voicemails usually share as `.m4a`/`.amr`. The app
  stores whatever you send and serves it back with its original type. `.m4a`
  plays inline in the dashboard; some `.amr` files may only be downloadable in
  the browser — either way the original is preserved as evidence.
- **Optional fields:** the endpoint also accepts `received_at` (ISO 8601) and
  `message_body` (a transcript) as additional form fields if you want to capture
  them in the Shortcut.
- **Security:** anyone with the URL *and* the token can post a voicemail, so
  treat the token like a password. Rotate it by changing the env var.
