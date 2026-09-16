# APK Automation Bot — Render Cloud Test

This project is a **separate Render cloud/test version** of the APK Automation Bot.

Production is NOT used here.

## Architecture

Telegram Test Bot
→ Telegram Local Bot API (`--local`) inside the same Render container
→ temporary APK file
→ GitHub Release in `downloadhub-official/apk-automation-render`
→ GPLinks/Oii/Ouo + direct GitHub link
→ Blogger

Render's public web port receives Telegram webhooks. The Local Bot API stays
private on `127.0.0.1:8081` and stores files inside `/var/lib/telegram-bot-api`.

Telegram's Local Bot API removes the normal 20 MB download restriction and
supports uploads up to 2000 MB, subject to Telegram's current limits.
This is why the Render container includes the Local Bot API server.

## GitHub Release behavior

The bot uses **one fixed GitHub Release** for all Render test APKs.

Default Release:
- Tag: `render-test-v1`
- Title: `Render Test`

For every APK:
1. Find the existing `render-test-v1` Release.
2. If the APK filename already exists, replace that asset.
3. Otherwise add the APK as a new asset in the same Release.
4. Verify the uploaded asset name and size.

So you do **not** create a new tag or Release for every APK.

**Important:** the `render-test-v1` Release must be mutable. A published GitHub
immutable Release cannot accept new or replacement assets. If the current
`render-test-v1` Release was created as immutable, recreate/use a mutable
`render-test-v1` Release before testing.

## Important Render limitation

Render Free web services have an ephemeral filesystem and can spin down after
15 minutes without inbound traffic. A restarted/spun-down service loses temporary
files. Therefore GitHub Release is the permanent APK storage; Render is only the
temporary processing server.

For a 200–400 MB test, keep the service awake during the test and avoid
redeploying while an APK is being processed.

## Security

Never put the Telegram token, GitHub token, Google token JSON, or shortener keys
inside the repository.

Use Render Environment Variables / Secrets.

## Required Render variables

See `RENDER_SETUP.md`.
