# Islamabad Club Golf Scoring App

This is a lightweight Python web app for a golf day with up to 20 players split across multiple flights.

## Features

- Gross scoring by hole
- Automatic handicap stroke allocation by stroke index
- Automatic net score calculation
- Automatic Stableford points calculation
- Up to 4 players per flight
- Full flight scorecard entry with players in columns and holes in rows
- Separate tabs for setup, scoring, and leaderboard
- Realtime leaderboard updates across open browsers using server-sent events
- Supabase-backed persistent storage for deployment
- Local JSON fallback for offline/local use

## Run Locally

Without Supabase:

```bash
python3 app.py
```

With Supabase:

1. Create a Supabase project.
2. Run the SQL in `supabase_schema.sql` in the Supabase SQL editor.
3. Copy `.env.example` to `.env` or export the same variables in your shell.
4. Start the app:

```bash
export SUPABASE_URL="https://your-project-ref.supabase.co"
export SUPABASE_SERVICE_ROLE_KEY="your-service-role-key"
export SUPABASE_TABLE="game_state"
python3 app.py
```

Then open `http://localhost:8000`.

## Deploy Online

### Recommended: Render + Supabase

Vercel is not a good fit for this app because it uses a long-running Python server and live event streaming for realtime updates. Render or Railway are a better match.

#### 1. Create Supabase storage

1. Create a new Supabase project.
2. Open the SQL editor.
3. Paste in the contents of `supabase_schema.sql`.
4. Run the SQL.

#### 2. Push this app to GitHub

Push this folder to a GitHub repo.

#### 3. Create a Render Web Service

1. In Render, click `New` -> `Web Service`.
2. Connect your GitHub repo.
3. Render will detect `render.yaml`.
4. Add these environment variables in Render:
   - `SUPABASE_URL`
   - `SUPABASE_SERVICE_ROLE_KEY`
   - `SUPABASE_TABLE` set to `game_state`
5. Deploy.

#### Important

- Use the `service role key` on the server only. Do not expose it in frontend code.
- The app will use Supabase automatically when those env vars are present.
- If the env vars are missing, it falls back to local file storage.

## How It Works

1. Add players, handicap, and flight allocation in the setup tab.
2. Save the tournament setup.
3. In the scoring tab, choose a flight and fill the scorecard grid.
4. The leaderboard tab updates live for all connected browsers.
