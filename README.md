# Telegram Bot Manager (Livegram-style) — for Botkeep

One **Manager Bot**; users connect their own bots with a BotFather token and manage commands, auto-responses,
welcome messages, buttons, broadcasts, users, analytics and (optional) sandboxed Python scripts.
Async Python (aiogram 3 + asyncpg), PostgreSQL, optional Redis. All managed bots run as asyncio tasks inside
**one process** (no process-per-bot).

## Layout
```
app/main.py                 entrypoint (migrations → identity → bots → web server → manager polling)
app/bot/                    Manager Bot UI (handlers, keyboards, middleware, wizard states)
app/manager/                identity (getMe), token validation, attribution, bot runtime, child update handler
app/services/               broadcast, analytics, matching, variables, script sandbox client
app/workers/script_runner.py  isolated, resource-limited script process
app/database/               pool, migrations (SQL), repositories
app/security/               token encryption, validators, rate limits, redacting JSON logs
```

## Environment variables (`.env.example`)
`DATABASE_URL`, `MANAGER_BOT_TOKEN`, `OWNER_ID`, `ENCRYPTION_KEY` (required); `REDIS_URL`, `MAX_BOTS_PER_USER`,
`WEBHOOK_BASE_URL`, `PORT`, `LOG_LEVEL`, `DB_POOL_MIN/MAX`, `MEDIA_MAX_BYTES` (optional).

Generate the key: `python -m app.security.keygen`. **Back it up** — without it stored bot tokens are unreadable.

## Deploy on Botkeep
I could only verify these points from botkeep.cloud's public page (Python, PostgreSQL and Redis profiles; GitHub or ZIP
deploys; env vars managed in the panel; each database uses one server slot). Panel labels may differ — check
https://botkeep.cloud/docs.

1. Create a bot with @BotFather → this is the **Manager Bot**; copy its token. Get your numeric ID (e.g. @userinfobot) → `OWNER_ID`.
2. Create a **PostgreSQL** server in Botkeep and copy its connection string → `DATABASE_URL`.
   The free plan has **1 slot**, so app + database needs a plan with 2+ slots (Botkeep currently advertises a
   3-slot Halloween promotion; verify terms on their site).
3. Create a **Python** server: upload this folder as a ZIP (or connect a GitHub repo).
4. Set the start command to `python main.py` (root `main.py`; the `Procfile` has the same) and make sure `requirements.txt` is installed
   (see Botkeep docs for how dependencies are installed).
5. Add env vars: `DATABASE_URL`, `MANAGER_BOT_TOKEN`, `OWNER_ID`, `ENCRYPTION_KEY` (+ optional ones).
6. Start. Migrations run automatically at boot. Send `/start` to the Manager Bot; `/owner` opens the owner panel.

Resources: free tier is 512 MB / 0.5 vCPU. Polling many bots works, but webhook mode scales better
(set `WEBHOOK_BASE_URL` to the public HTTPS URL; per-bot toggle under Settings → Advanced).
Botkeep states secrets are readable by their infrastructure admins and the app code, so treat `ENCRYPTION_KEY` as only
protecting against database leaks/backups.

## Behaviour notes
* **Attribution**: text is built from the Manager Bot's live `getMe` username (refreshed every 10 min); nothing hardcoded.
  A bot cannot message a user who never pressed Start, so at connection the manager tries to DM the owner *through the new bot*;
  if Telegram refuses, it is sent automatically the first time the owner messages their bot. Failures are logged, never block connection.
* **Media**: Telegram `file_id`s are bot-specific, so uploaded media is stored in PostgreSQL and the per-bot `file_id` is cached on first send.
* **Ownership**: every manager action goes through `BotRepo.get_owned(bot_id, user_id)`; child records are always queried by the verified `bot_id`.
* **Broadcasts**: recipient snapshot, 20 msg/s per bot, honours `retry_after`, resumes after restart.

## ⚠️ Python scripts — read before enabling
Scripts are **off by default** (Owner Panel → Features). They run in a separate process with CPU/memory/time/FD limits,
no fork, empty environment, temp cwd, AST allow-listing of imports/attributes and restricted builtins, and cannot reach the bot token
(they only *request* replies). This is defence in depth, **not a hard security boundary**: without containers/namespaces
(unavailable on Botkeep as far as I can tell) network blocking is by omission (no socket module), not by the OS.
Enable only for trusted users, or run the worker in a container/nsjail/gVisor for untrusted ones.

## Not covered / honest gaps
* Not run against live Telegram (no token here). Database layer and sandbox were tested against PostgreSQL 16.
* No automated test suite or Docker image yet.
