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

---

# Screenshot + voicemail in one incident (two-step flow)

The iPhone voicemail screen shows the number, time, and transcript all at once —
great evidence. Because you can't share the screenshot and the audio in a single
tap, this uses **two shortcuts run back to back**, and the server links them
automatically (no incident id to copy around):

1. **Screenshot first** → creates the incident (you type the number once).
2. **Voicemail second** → its audio auto-attaches to that same incident,
   because the server links new audio to the most recent voicemail incident that
   still has no audio.

## Shortcut A — "Log VM Screenshot"

This reads the caller's number **off the screenshot automatically** using iOS's
built-in text recognition, so you don't type anything.

1. New shortcut → Settings (ⓘ): **Show in Share Sheet**, accept **Images** and
   **Files**.
2. **Extract Text from Image** → set its input to **Shortcut Input** (the
   screenshot). This is Apple's on-device OCR; it produces the screen's text,
   including the number at the top.
3. **Get Contents of URL:**
   - URL: `https://YOUR-APP.up.railway.app/api/voicemails/screenshot?token=YOUR_UPLOAD_TOKEN`
   - Method `POST`, Request Body `Form`:
     | Key | Type | Value |
     | --- | --- | --- |
     | `file` | File | **Shortcut Input** (the screenshot) |
     | `ocr_text` | Text | **Extracted Text** (from step 2) |

From `ocr_text` the server auto-fills the **number**, the **timestamp**, the
**caller name** (when shown), the **transcript** (tab-bar/button chrome stripped
out), and the **voicemail length**. It also flags automated/telemarketing
signals — a "press N" menu, opt-out/DNC language, and solicitation keywords —
recording them in the incident's notes, and sets the *prerecorded* flag when
there's a clear automated-message signal. The full OCR text is kept as reference.
(If recognition ever misses, add a `from_number` field or fix it on the detail
page.)

## Shortcut B — "Log VM Audio"

1. New shortcut → Settings (ⓘ): **Show in Share Sheet**, accept **Media** and
   **Files**.
2. **Get Contents of URL:**
   - URL: `https://YOUR-APP.up.railway.app/api/voicemails/audio?token=YOUR_UPLOAD_TOKEN`
   - Method `POST`, Request Body `Form`:
     | Key | Type | Value |
     | --- | --- | --- |
     | `file` | File | **Shortcut Input** (the audio) |

   No number needed — it auto-links to the screenshot you just uploaded.

## Use it

1. On the voicemail screen, take a **screenshot** (side + volume-up).
2. Open the screenshot → **Share → Log VM Screenshot** (the number is read
   automatically — no typing).
3. Right away, on the same voicemail → **Share → Log VM Audio**.

Both land on one incident; open it from the dashboard (**view**) to see the
screenshot and play the audio together, and to set the TCPA facts.

> **Do the audio step soon after the screenshot.** Auto-linking attaches the
> audio to the most recent voicemail incident still missing audio (within ~12
> hours). If you ever get them out of order, just open the incident and use
> **Add evidence** to attach the file manually.

## Notes

- **File format:** iPhone voicemails usually share as `.m4a`/`.amr`. The app
  stores whatever you send and serves it back with its original type. `.m4a`
  plays inline in the dashboard; some `.amr` files may only be downloadable in
  the browser — either way the original is preserved as evidence.
- **Optional fields:** the upload endpoints also accept `received_at` (ISO 8601)
  and `message_body` (a transcript) as extra form fields if you want to capture
  them in a Shortcut.
- **Security:** anyone with the URL *and* the token can post, so treat the token
  like a password. Rotate it by changing the env var.
