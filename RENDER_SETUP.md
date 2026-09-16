# Render Setup — APK Automation Bot Cloud Test

## 1. Repository

Use ONLY the separate test repository:

`downloadhub-official/apk-automation-render`

Do NOT connect the Production repository.

## 2. Render service

Create:

- Type: **Web Service**
- Source: GitHub
- Repository: `downloadhub-official/apk-automation-render`
- Branch: `main`
- Runtime: Docker
- Dockerfile: `Dockerfile`
- Public port: Render's `PORT` (the code reads it automatically)
- Health check path: `/health`

Render web services must bind the public HTTP server to `0.0.0.0` and normally
use the `PORT` environment variable.

## 3. Telegram

Use the SECOND/TEST Telegram bot token.

This version runs a Telegram Local Bot API server inside the same Render container.
You need:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_API_ID`
- `TELEGRAM_API_HASH`

Get `TELEGRAM_API_ID` and `TELEGRAM_API_HASH` from Telegram's official API
application page.

Do NOT use the Production bot token.

## 4. Webhook

Render automatically provides:

`RENDER_EXTERNAL_URL`

The bot uses:

`RENDER_EXTERNAL_URL + /telegram`

Set:

`WEBHOOK_PATH=/telegram`

Create a random secret for:

`WEBHOOK_SECRET`

Example format:

`RenderTestWebhook_2026_ABC123`

Telegram webhook requests are checked using the
`X-Telegram-Bot-Api-Secret-Token` header.

## 5. GitHub test repository

Set:

`GITHUB_OWNER=downloadhub-official`

`GITHUB_REPO=apk`

`GITHUB_TARGET_BRANCH=main`

`GITHUB_TOKEN=<token with Contents: Read and write>`

The bot uses **one fixed Release for every APK**:

`GITHUB_RELEASE_TAG=render-test-v1`

You do **not** create a new tag or Release for each APK. Each new APK is added
as another asset inside that same Release. If the same filename already exists,
the bot replaces that asset.

**Important:** this Release must be mutable. Do not use a published immutable
Release for this test, because immutable published Releases cannot receive new
or replacement assets.

## 6. Blogger

The current code can use the same Blogger page IDs from the source project,
but **do not deploy with production Blogger page IDs if you want zero impact on
Production content**.

For a completely isolated test, create/use separate Blogger test pages and set:

- `BLOGGER_PAGE_MOVIEBOX`
- `BLOGGER_PAGE_REMINI`
- `BLOGGER_PAGE_SNAPTUBE`
- `BLOGGER_PAGE_DUOLINGO`
- `BLOGGER_PAGE_LARK_PLAYER`
- `BLOGGER_PAGE_NODEVIDEO`

Also set:

`BLOG_ID`

### Google OAuth on Render

Render has no browser-based OAuth flow in this bot.

Provide the already-authorized `token.json` contents as:

`GOOGLE_TOKEN_JSON`

The JSON must contain a valid refresh token for Blogger API access.

If the token is invalid/expired and cannot refresh, the Blogger stage will stop
without intentionally changing Blogger.

## 7. Shorteners

Set whichever providers you actually use:

- `GPLINKS_API_KEY`
- `OII_API_KEY`
- `OUO_API_KEY`

All three providers are required by this final test build. If any one key is missing, the job stops before Blogger is changed.

## 8. Other variables

Recommended:

`ALLOWED_CHAT_ID=<your test Telegram chat ID>`

`MAX_APK_BYTES=0`

`HTTP_CONNECT_TIMEOUT=60`

`HTTP_READ_TIMEOUT=3600`

`GITHUB_MAKE_LATEST=false`

## 9. Deploy

Push this Render version to the `main` branch of:

`downloadhub-official/apk-automation-render`

Render deploys from that branch.

After deploy, check:

`https://YOUR-RENDER-DOMAIN/health`

It should return:

`ok`

Then check Render logs for:

- `Telegram Local Bot API is ready.`
- `Starting Render webhook bot...`
- `Telegram webhook set to ...`
- `Render public webhook server listening ...`

## 10. Test order

Do not start with the largest APK.

Use:

1. 20–50 MB
2. 100 MB
3. 200 MB
4. 300 MB
5. ~398 MB

For every successful job the flow should be:

Telegram
→ Local Bot API
→ temporary Render file
→ new GitHub Release
→ APK asset verification
→ short links
→ Blogger update
→ final verification

## 11. Important

Render Free web services are temporary test infrastructure. They can spin down
after 15 minutes without inbound traffic, and their local filesystem is
ephemeral. Do not treat Render's disk as permanent APK storage. GitHub Release
is the permanent storage target.

For long tests that may exceed the free service's idle window, a paid Render
service is more reliable because paid services do not use the Free idle
spin-down behavior.

## 12. Production safety

This Render project must use:

- separate Telegram bot
- separate GitHub repository
- separate Render service
- separate test credentials

Do not copy Production `config.py`, `.env`, Telegram token, or other secrets
into this project.
