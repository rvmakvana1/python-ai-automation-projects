from telethon import TelegramClient, events, errors
from openai import OpenAI
import asyncio
import csv
import os
import random

# --- 1. CONFIGURATION (Add your credentials here) ---
# NOTE: Never share your actual keys on public platforms like GitHub.
api_id = 1234567                  # <--- Replace with your Telegram API ID
api_hash = 'YOUR_API_HASH_HERE'  # <--- Replace with your Telegram API HASH
phone = '+910000000000'           # <--- Replace with your Phone Number

# OPENAI CONFIGURATION
openai_api_key = "YOUR_OPENAI_API_KEY_HERE"  # <--- Replace with your OpenAI Key
ai_client = OpenAI(api_key=openai_api_key)

# OFFICIAL GROUP LINK (Global Community)
bot_link = "https://t.me/your_group_link"  # <--- Replace with your Group Link

# Initial Outreach Message
initial_msg = "Hello, How Are You?"

# --- 2. PERMANENT MEMORY SYSTEM 📓 ---
# This file tracks users who have already been contacted to avoid duplicates.
sent_filename = "sent_users.txt"
contacted_users = set()       # Set to store contacted user IDs
user_chat_history = {}        # Dictionary to store conversation context

# Load previous memory from file
if os.path.exists(sent_filename):
    try:
        with open(sent_filename, "r", encoding="utf-8") as f:
            for line in f:
                user_data = line.strip()
                if user_data:
                    contacted_users.add(user_data)
        print(f"📖 Loaded memory: {len(contacted_users)} users already contacted.")
    except Exception as e:
        print(f"⚠️ Memory Read Error: {e}")

client = TelegramClient('session_live_master', api_id, api_hash)

# --- 3. AI CORE ENGINE (Persona: Digital Nomad & Trader) 🧠 ---
def get_chatgpt_reply(user_id, user_message):
    try:
        # Initialize History & Define System Instructions
        if user_id not in user_chat_history:
            user_chat_history[user_id] = [
                {"role": "system", "content": f"""
# IDENTITY & PERSONA
You are **Ranjit Makvana**, a successful Crypto Trader and Digital Nomad.
* **Vibe:** You live a freedom-based lifestyle—traveling globally and working from cafes.
* **Goal:** Build genuine friendships first. Later, invite them to your "Global Crypto Community".

# SMART LANGUAGE PROTOCOL (MIRROR RULE)
1. **DEFAULT:** Use conversational Global English (e.g., "bro", "mate").
2. **MIRROR:** If the user speaks Hindi or Hinglish, instantly switch to match their language.

# THE 7-MESSAGE STRATEGY
* **Phase 1-2:** Social talk & Travel.
* **Phase 3-4:** Transition to Work/Trading.
* **Phase 5-6:** Identify Pain Points (Job routine, trading losses).
* **Phase 7+:** Introduce the Solution (Community link: {bot_link}).
                """}
            ]
        
        user_chat_history[user_id].append({"role": "user", "content": user_message})

        response = ai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=user_chat_history[user_id]
        )
        
        reply_text = response.choices[0].message.content
        user_chat_history[user_id].append({"role": "assistant", "content": reply_text})
        return reply_text

    except Exception as e:
        print(f"❌ AI Error: {e}")
        return "Network is a bit weak here. Text you back in a minute!"

# --- 4. THE LISTENER (Handles Incoming Responses) ---
@client.on(events.NewMessage(incoming=True))
async def handle_new_message(event):
    if event.is_private:
        sender = await event.get_sender()
        if not sender: return
        
        sender_id = sender.id
        username = sender.username
        
        # Only reply to users we've already contacted
        is_contacted = str(sender_id) in contacted_users or (username and username in contacted_users)

        if is_contacted:
            user_text = event.raw_text
            print(f"\n📩 Reply from {sender.first_name}: {user_text}")

            ai_reply = get_chatgpt_reply(sender_id, user_text)

            # Simulate human behavior with typing delay
            delay = random.randint(10, 20) 
            print(f"⏳ Typing... ({delay}s)...")
            async with client.action(sender_id, 'typing'):
                await asyncio.sleep(delay)
            
            try:
                await event.reply(ai_reply)
                print(f"✅ AI Sent: {ai_reply}")
            except Exception as e:
                print(f"❌ Error: {e}")

# --- 5. THE SENDER (Targeting & Daily Limits) 🚀 ---
async def send_initial_messages():
    input_file = 'members.csv'
    if not os.path.exists(input_file):
        print("❌ CSV not found!")
        return

    users_to_contact = []
    try:
        with open(input_file, encoding='UTF-8') as f:
            rows = csv.reader(f, delimiter=',', lineterminator="\n")
            next(rows, None)
            for row in rows:
                if len(row) >= 2 and row[1].strip():
                    users_to_contact.append(row[1].strip())
    except Exception as e:
        print(f"❌ CSV Error: {e}")
        return

    # Filter: Target only new leads
    new_targets = [u for u in users_to_contact if u not in contacted_users]
    print(f"🎯 New Targets Found: {len(new_targets)}")

    daily_limit = 40   # Maximum new messages per 24 hours
    daily_count = 0    

    for target_username in new_targets:
        if daily_count >= daily_limit:
            print(f"⏳ Daily limit of {daily_limit} reached. Pausing for 24h.")
            await asyncio.sleep(86400)
            daily_count = 0

        try:
            sent_msg = await client.send_message(target_username, initial_msg)
            
            # Save to memory immediately
            user_id_str = str(sent_msg.peer_id.user_id)
            contacted_users.add(target_username)
            contacted_users.add(user_id_str)
            
            with open(sent_filename, "a", encoding="utf-8") as f:
                f.write(f"{target_username}\n{user_id_str}\n")
            
            daily_count += 1
            wait_time = random.randint(40, 80)
            await asyncio.sleep(wait_time)
            
        except errors.PeerFloodError:
            print("🚨 Flood Error! Stopping for safety.")
            break
        except Exception as e:
            print(f"❌ Failed to send to {target_username}: {e}")

# --- MAIN RUNNER ---
async def main():
    print("🔌 Connecting to Telegram...")
    await client.start(phone=phone)
    print("✅ System Ready!")
    
    await send_initial_messages()
    print("👂 Listening Mode Active...")
    await client.run_until_disconnected()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Stopped.")