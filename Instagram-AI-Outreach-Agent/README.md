# PromoPe Instagram AI Outreach Agent

An autonomous Instagram DM outreach agent that finds leads from a CSV, sends personalized opening messages, and replies to incoming DMs in real time using GPT-4o-mini. Built for PromoPe — an influencer-brand collaboration platform.

---

## 1. Project Overview

This bot automates the cold outreach pipeline for influencer recruitment on Instagram:

- Reads a list of target creators from a CSV file (username, category, bio).
- Sends a tailored "hook" message to each new lead.
- Listens for replies in the Instagram inbox.
- Generates context-aware responses through an AI persona ("Rahul, Senior Outreach Specialist").
- Maintains per-user conversation history so each chat stays coherent across cycles.
- Persists session, leads, and contacted users to disk so it can resume safely after restarts.

It is designed to run as a long-lived process — outreach happens slowly in the background while inbox checks run on a fast heartbeat.

---

## 2. Key Features

- **AI Conversations** — Uses OpenAI `gpt-4o-mini` with a strict system prompt that defines the agent's identity, goals, and topic guardrails (refuses off-topic questions, stays on PromoPe pitch).
- **Mirror Protocol** — The agent detects the language style of the user (English vs. Hindi/Hinglish) and mirrors it to build rapport. Hinglish replies are kept short (2–3 sentences) for a personal feel.
- **Anti-Ban System** —
  - Persistent session via `ig_session.json` (avoids re-login flags).
  - Randomized human-like typing delays (5–10s) before each reply.
  - Throttled outreach window of 6–10 minutes between new cold messages.
  - One outreach per cycle — never bursts.
- **Real-Time Listener** — Polls `direct_threads` every 30 seconds. Only replies when the most recent message in a thread is from the user (not from the bot itself), preventing self-loops.
- **CSV Lead Management** —
  - `instagram_leads.csv` is the input source (columns: `username`, `category`, `bio`).
  - Already-contacted users tracked in `sent_insta_users.txt` so leads are never messaged twice.
  - Lead context (category, bio) cached in `lead_info.json` and used to enrich the AI's system prompt for each conversation.

---

## 📸 Live Demo — Real Conversation

The following screenshots show the bot in action, conducting a real outreach conversation on Instagram:

**Screenshot 1:** Bot initiates contact, identifies lead as digital creator
**Screenshot 2:** Bot qualifies lead interest in brand sponsorships and provides next steps

![Demo Conversation 1](assets/demo_conversation_1.jpg)
![Demo Conversation 2](assets/demo_conversation_2.jpg)

---

## 3. Tech Stack

| Layer | Tool |
|---|---|
| Language | Python 3.9+ |
| Instagram API | [`instagrapi`](https://github.com/subzeroid/instagrapi) (private API client) |
| AI Model | OpenAI `gpt-4o-mini` via the official `openai` SDK |
| Config | `python-dotenv` for environment variable loading |
| Storage | Flat files — JSON for session/leads, CSV for input, TXT for the sent-list |

---

## 4. Project Structure

```
PromoPe_Instagram_Agent/
├── insta_agent.py          # Main agent — login, listener, sender, runner loop
├── instagram_leads.csv     # Input: leads to contact (username, category, bio)
├── ig_session.json         # Cached Instagram login session (auto-generated)
├── lead_info.json          # Cached lead context used by the AI prompt
├── sent_insta_users.txt    # Append-only log of users already contacted
├── .env                    # Local secrets (NEVER commit)
├── .env.example            # Template showing required env vars
├── .gitignore              # Excludes secrets, session, and lead data
└── README.md               # You are here
```

**File-by-file:**

- **`insta_agent.py`** — The whole agent. Entry point is `main()`, which logs in, syncs leads from CSV into memory, then enters the heartbeat loop (`check_for_replies` + throttled `run_outreach`).
- **`instagram_leads.csv`** — You provide this. UTF-8 with BOM is supported. Required columns: `username`, `category`, `bio`.
- **`ig_session.json`** — Created on first successful login. Reused on subsequent runs to skip credential-based login (reduces Instagram challenge prompts).
- **`lead_info.json`** — Mirror of the CSV in JSON form, used as a fast lookup when generating replies.
- **`sent_insta_users.txt`** — One username per line. Loaded on outreach to skip already-contacted users.
- **`.env`** — Holds `INSTA_USERNAME`, `INSTA_PASSWORD`, `OPENAI_KEY`. Gitignored.
- **`.env.example`** — Same keys, placeholder values. Safe to commit.

---

## 5. Setup Instructions

### Prerequisites
- Python 3.9 or newer
- An Instagram account (a dedicated outreach account is recommended — do not use your personal account)
- An OpenAI API key with access to `gpt-4o-mini`

### Install dependencies

```bash
pip install instagrapi openai python-dotenv
```

### Configure environment

1. Copy the example env file:
   ```bash
   cp .env.example .env
   ```
2. Open `.env` and fill in real values:
   ```
   INSTA_USERNAME=your_instagram_username
   INSTA_PASSWORD=your_instagram_password
   OPENAI_KEY=sk-...
   ```

### Prepare your leads file

Create `instagram_leads.csv` in the project root with this header row:

```csv
username,category,bio
some_creator,fashion influencer,Mumbai-based fashion blogger
another_user,fitness coach,Helping you get stronger every day
```

### Run the agent

```bash
python insta_agent.py
```

On first run, Instagram may issue a login challenge — complete it in the app, then re-run. Subsequent runs reuse `ig_session.json`.

---

## 6. How It Works

```
                 ┌──────────────────────┐
                 │      main() boot     │
                 │  • load .env         │
                 │  • login_user()      │
                 │  • sync CSV → memory │
                 └──────────┬───────────┘
                            │
                            ▼
       ┌────────────────────────────────────────┐
       │           Main Loop (forever)          │
       │                                        │
       │  ┌──────────────────────────────────┐  │
       │  │  check_for_replies()             │  │
       │  │   • fetch last 10 DM threads     │  │
       │  │   • if last msg is from user →   │  │
       │  │       get_promope_reply() (GPT)  │  │
       │  │       sleep 5–10s (human delay)  │  │
       │  │       cl.direct_answer(...)      │  │
       │  └──────────────────────────────────┘  │
       │                                        │
       │  ┌──────────────────────────────────┐  │
       │  │  run_outreach()                  │  │
       │  │   (only if 6–10 min has passed)  │  │
       │  │   • pick next uncontacted lead   │  │
       │  │   • cl.direct_send(hook message) │  │
       │  │   • append to sent_insta_users   │  │
       │  └──────────────────────────────────┘  │
       │                                        │
       │           sleep 30s (heartbeat)        │
       └────────────────────────────────────────┘
```

**Conversation memory:** `user_chat_history` is keyed by thread ID and holds the full message list per conversation, so GPT sees the entire back-and-forth on every reply (not just the last message).

**System prompt injection:** When a new thread starts, the lead's `category` and `bio` from `lead_info.json` are injected into the system prompt so the AI references their niche naturally.

---

## 7. Security Notes

- **`.env` is gitignored.** Never commit it. Never paste it into chat tools, screenshots, or screen shares.
- **Rotate any leaked secret immediately.** If credentials ever appear in source, history, logs, or a screen recording, treat them as compromised — change the Instagram password and revoke the OpenAI key at platform.openai.com/api-keys before doing anything else.
- **`ig_session.json` is sensitive.** It contains login state and can be used to impersonate the account. Keep it gitignored and off shared drives.
- **Lead data is sensitive too.** `instagram_leads.csv`, `lead_info.json`, and `sent_insta_users.txt` contain third-party usernames and bios — treat them as PII and keep them gitignored.
- **Use a dedicated Instagram account.** Aggressive automation can trigger action blocks or permanent bans. Don't run this on an account you can't afford to lose.
- **Rate limits matter.** The 6–10 minute outreach window and 30s inbox heartbeat are conservative on purpose. Lowering them increases ban risk significantly.

---

## ⚠️ Disclaimer

This project is for **educational and research purposes only**.
The author does not encourage violation of Instagram's Terms of Service.
This tool was built to demonstrate AI-powered conversation systems and Python automation skills.
Use at your own risk. Over-automation can lead to account restrictions or bans.
The author is not responsible for any misuse of this tool.
