import os
import csv
import time
import random
import json
from dotenv import load_dotenv
from instagrapi import Client
from openai import OpenAI

# --- 1. CONFIGURATION ---
load_dotenv()
INSTA_USERNAME = os.getenv("INSTA_USERNAME")
INSTA_PASSWORD = os.getenv("INSTA_PASSWORD")
OPENAI_KEY = os.getenv("OPENAI_KEY")

ai_client = OpenAI(api_key=OPENAI_KEY)
cl = Client()

# --- 2. MEMORY & DATA SYSTEM ---
SENT_FILE = "sent_insta_users.txt"
LEAD_INFO_FILE = "lead_info.json"
SESSION_FILE = "ig_session.json"

user_chat_history = {}
lead_data_memory = {}

# पुराने डेटा को लोड करना
if os.path.exists(LEAD_INFO_FILE):
    with open(LEAD_INFO_FILE, "r") as f:
        lead_data_memory = json.load(f)

def login_user():
    """Instagram सुरक्षित लॉगिन सिस्टम"""
    if os.path.exists(SESSION_FILE):
        cl.load_settings(SESSION_FILE)
        try:
            cl.login(INSTA_USERNAME, INSTA_PASSWORD)
            print("✅ Session Loaded: लॉगिन सफल!")
        except Exception:
            cl.login(INSTA_USERNAME, INSTA_PASSWORD)
    else:
        cl.login(INSTA_USERNAME, INSTA_PASSWORD)
        cl.dump_settings(SESSION_FILE)
        print("✅ New Session Created!")

# --- 3. AI BRAIN (Mirror Protocol + 7-Message Logic) ---
def get_promope_reply(user_id, user_message, username):
    info = lead_data_memory.get(username, {"category": "digitalcreator", "bio": ""})
    
    if user_id not in user_chat_history:
        user_chat_history[user_id] = [
            {"role": "system", "content": f"""
# IDENTITY & PURPOSE
You are Rahul, a Senior Outreach Specialist for PromoPe—India's #1 platform that bridges the gap between Influencers and Brands.
Your goal is to build interest, explain how PromoPe helps them earn more/grow, and get them to check the website.

# CONTEXT (User Data)
Target Username: {username}
Profile Category: {info['category']}
Profile Bio: {info['bio']}

# CONVERSATION STRATEGY (The Flow)
1. **The Hook:** Acknowledge their niche (from bio/category). Be friendly and appreciative of their content.
2. **The Benefit:** Explain that PromoPe connects creators with high-paying brands automatically so they can focus on content, not hunting for deals.
3. **The Solution:** If they show interest or ask "How?", introduce PromoPe and provide the plain link: https://promope.com/ (CRITICAL: Do not use brackets or markdown, send only the plain URL so it is clickable).
4. **Professionalism:** Be polite, professional, yet warm like a partner.

# TOPIC GUARDRAILS (Strict!)
- **PROMOPE ONLY:** Talk ONLY about influencer marketing, brand deals, and PromoPe.
- **REFUSE OFF-TOPICS:** If the user asks about Politics, GK, Math, or anything unrelated to your work, politely decline. 
  - *Example:* "Haha, I'd love to help but my brain is 100% focused on brand collaborations right now! Let's get back to your growth on Instagram."

# LANGUAGE PROTOCOL
- Default is English.
- **MIRROR RULE:** If they speak in Hindi or Hinglish, you MUST switch to Hinglish to build a personal connection and trust. Keep replies short (2-3 sentences max).
            """}
        ]
    
    user_chat_history[user_id].append({"role": "user", "content": user_message})
    response = ai_client.chat.completions.create(model="gpt-4o-mini", messages=user_chat_history[user_id])
    reply = response.choices[0].message.content
    user_chat_history[user_id].append({"role": "assistant", "content": reply})
    return reply

# --- 4. THE LISTENER (Incoming Messages) ---
def check_for_replies():
    print("👀 Checking for new replies in Inbox...")
    try:
        threads = cl.direct_threads(amount=10)
        for thread in threads:
            if not thread.messages: continue
            last_msg = thread.messages[0] # Fixed: 'items' changed to 'messages' [cite: 2026-03-03]
            
            # अगर आखिरी मैसेज यूजर का है
            if str(last_msg.user_id) != str(cl.user_id):
                username = thread.users[0].username
                if username in lead_data_memory:
                    print(f"📩 New reply from {username}: {last_msg.text}")
                    ai_reply = get_promope_reply(thread.id, last_msg.text, username)
                    
                    time.sleep(random.randint(5, 10)) # Human typing delay
                    cl.direct_answer(thread.id, ai_reply)
                    print(f"✅ AI Replied: {ai_reply}")
    except Exception as e:
        print(f"❌ Listener Error: {e}")

# --- 5. THE SENDER (New Outreach) ---
def run_outreach():
    contacted_users = set()
    if os.path.exists(SENT_FILE):
        with open(SENT_FILE, "r") as f:
            contacted_users = set(line.strip() for line in f)

    try:
        with open('instagram_leads.csv', mode='r', encoding='utf-8-sig') as file:
            reader = csv.DictReader(file)
            for row in reader:
                # कॉलम नाम क्लीनिंग
                row = {k.strip().lower(): v for k, v in row.items()}
                target_user = row.get('username')

                if not target_user or target_user in contacted_users:
                    continue

                # मेमोरी में जानकारी जोड़ें
                lead_data_memory[target_user] = {"category": row.get('category', 'digitalcreator'), "bio": row.get('bio', '')}
                
                try:
                    print(f"🚀 Sending Hook to {target_user}...")
                    user_id = cl.user_id_from_username(target_user)
                    msg = f"Hey {target_user}, saw your profile as a {row.get('category')}. Great content!"
                    cl.direct_send(msg, [user_id])
                    
                    with open(SENT_FILE, "a") as f: f.write(target_user + "\n")
                    print(f"✅ Message sent successfully!")
                    return True # एक मैसेज के बाद ब्रेक लें
                except Exception as e:
                    print(f"❌ Error with {target_user}: {e}")
                    return False
    except Exception as e:
        print(f"❌ CSV Error: {e}")
    return False

# --- 6. MAIN RUNNER (Speed Optimized Version) ---
def main():
    login_user()
    
    # शुरुआती डेटा सिंक (CSV से जानकारी लोड करना)
    with open('instagram_leads.csv', mode='r', encoding='utf-8-sig') as file:
        reader = csv.DictReader(file)
        for row in reader:
            row = {k.strip().lower(): v for k, v in row.items()}
            lead_data_memory[row['username']] = {"category": row['category'], "bio": row['bio']}
    
    with open(LEAD_INFO_FILE, "w") as f: json.dump(lead_data_memory, f)

    print("🤖 Agent is LIVE. Fast Reply Mode Active.")
    
    last_outreach_time = 0 # पिछला Outreach कब हुआ

    while True:
        # 1. रिप्लाई चेक करें (Fast Check: हर 30 सेकंड में)
        check_for_replies()
        
        # 2. नए लीड को मैसेज भेजें (Slow outreach: 6-10 मिनट का गैप)
        current_time = time.time()
        # random.randint(360, 600) मतलब 6 से 10 मिनट
        if current_time - last_outreach_time > random.randint(360, 600):
            print("🚀 Sending a new outreach message to next lead...")
            run_outreach()
            last_outreach_time = time.time()
        
        # 3. इनबॉक्स चेक करने की रफ़्तार (Heartbeat)
        print("⏳ Heartbeat: Checking inbox again in 30s...")
        time.sleep(30)
if __name__ == "__main__":
    main()