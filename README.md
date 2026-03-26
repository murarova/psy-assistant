# psy-assistant

Telegram AI calendar assistant using OpenAI Agents SDK and Google Calendar.

## Local Setup

1. Create and activate a virtual environment:
   - `python3 -m venv .venv && source .venv/bin/activate`
2. Install dependencies:
   - `pip install -e .`
3. Copy env template and fill values:
   - `cp .env.example .env`
4. Run:
   - `python app.py`

## Deploy to Railway

### 1. Prepare Google token secret

Run this locally after completing OAuth once:

```bash
base64 -i token.json | tr -d '\n'
```

Copy the output — you will paste it as `GOOGLE_TOKEN_BASE64` in Railway.

### 2. Push code to GitHub

```bash
git init
git add .
git commit -m "initial"
gh repo create psy-assistant --private --push --source=.
```

### 3. Deploy on Railway

1. Go to [railway.app](https://railway.app) and sign in.
2. Click **New Project → Deploy from GitHub repo** and select your repo.
3. Railway detects Python and uses `requirements.txt` automatically.
4. Go to your service → **Variables** tab and add:

| Variable | Value |
|---|---|
| `OPENAI_API_KEY` | your OpenAI key |
| `OPENAI_MODEL` | `gpt-4o-mini` |
| `TELEGRAM_BOT_TOKEN` | your Telegram bot token |
| `GOOGLE_CLIENT_ID` | your Google client ID |
| `GOOGLE_CLIENT_SECRET` | your Google client secret |
| `GOOGLE_CALENDAR_ID` | `primary` |
| `GOOGLE_TOKEN_PATH` | `token.json` |
| `GOOGLE_TOKEN_BASE64` | base64 output from step 1 |
| `TIMEZONE` | `Europe/Kyiv` |

5. Railway will redeploy automatically. The bot starts polling.

### Redeploy after code changes

```bash
git add . && git commit -m "update" && git push
```

Railway auto-redeploys on every push to main.
