# Python AI Automation Master Portfolio

Welcome to my central hub for **Advanced AI & Python Automation**. This repository showcases a collection of high-performance, autonomous systems designed to leverage **Artificial Intelligence (LLMs)** to solve real-world business challenges and streamline complex workflows.

---

## 🤖 Featured Project: Autonomous AI Telegram Outreach Agent

This is an end-to-end, enterprise-grade AI system built to automate lead generation and nurturing on Telegram. Moving beyond traditional "botting," this agent utilizes **Advanced NLP** to build rapport and convert leads through natural, human-centric conversations.

### **🚀 Core Innovations & Capabilities**

* **🧠 Smart "Mirror" Language Protocol:** The agent **dynamically detects the lead's language** in real-time. If a user responds in English, the AI stays in English; if they switch to **Hindi or Hinglish**, the AI instantly mirrors their tone to establish deep trust and rapport.
* **🛡️ Enterprise-Grade Anti-Ban Architecture:** Engineered for account longevity with multiple safety layers:
    * **Strict Rate Limiting:** Capped at **40 new leads per day** to simulate organic growth.
    * **Human-Behavior Simulation:** Implements **randomized typing delays (10-20s)** and variable response times.
* **💾 Persistent Smart Memory:** Using a localized `sent_users.txt` database, the agent ensures **zero redundancy**. It maintains a permanent record of interactions to guarantee that **no lead is ever contacted twice**, even after a system reboot.
* **☁️ 24/7 Cloud Autonomy (AWS VPS):** The agent is successfully deployed on an **AWS EC2 Windows VPS**, operating in **"Listening Mode" 24/7**. It handles replies in real-time without requiring manual intervention.

---

## 🛠️ Technical Stack & Infrastructure

* **Language:** **Python 3.14.3** (Optimized for latest async standards)
* **Core Libraries:** **Telethon** (MTProto API) & **OpenAI API** (GPT-4o-mini)
* **Database Management:** CSV-based lead ingestion with localized persistent memory.
* **Hosting Platform:** **AWS EC2 (T3.Medium Windows Server)**

---

## 📸 Live Proof of Concept (Sales Funnel)

The agent follows a high-conversion 7-step funnel. Below is the live interaction captured from the VPS production environment:

### **1. Rapport & Trust Building**
The bot initiates contact with a non-salesy icebreaker to establish its persona.
👉 **[View Phase 1 Screenshot](https://github.com/rvmakvana1/python-ai-automation-projects/blob/main/Crypto%20Guide%201.png)**

### **2. Identifying User Pain Points**
The AI identifies user struggles (e.g., the 9-to-5 grind or trading losses) and provides context-aware responses.
👉 **[View Phase 2 Screenshot](https://github.com/rvmakvana1/python-ai-automation-projects/blob/main/Crypto%20Guide%202.png)**

### **3. Strategic Conversion & Link Sharing**
Once interest is piqued, the bot shares the 'Global Community' link as a natural solution.
👉 **[View Phase 3 Screenshot](https://github.com/rvmakvana1/python-ai-automation-projects/blob/main/Crypto%20Guide%203.png)**

---

## 📂 Repository Assets

* 📜 **[lead_sender_2.py](https://github.com/rvmakvana1/python-ai-automation-projects/blob/main/lead_sender_2.py)**: The core Python engine and autonomous reply logic.
* 📄 **[LICENSE](./LICENSE)**: MIT Licensed for professional open-source standards.
* 🙈 **[.gitignore](./.gitignore)**: Configured to protect sensitive environment variables.

---

## 👨‍💻 Developer & Automation Specialist
**Ranjit Makvana**
*Specializing in AI-Driven Automation, Intelligent Agents, and Scalable Cloud Systems.*


# 🚀 WhatsApp-to-Gemini AI Automation Agency Bot

![WhatsApp Bot Flow & AI Posters](https://github.com/rvmakvana1/python-ai-automation-projects/blob/main/whatsapp%20automation.png?raw=true)

## 📌 Project Overview
This project is a fully automated, end-to-end "AI Creative Agency in a Bot." It acts as a digital sales consultant that interacts with customers via WhatsApp, gathers their business details, and uses an advanced browser-automation pipeline to command Google's Gemini AI. The result? A hyper-personalized, photorealistic 3D promotional poster delivered straight to the customer's WhatsApp in under a minute.

This project was built to demonstrate advanced browser automation, webhook handling, and AI prompt engineering without relying on expensive official image-generation APIs.

---

## 📂 Source Code Files (Explore the Code)
Here are the core components of the project. Click to view the source code:

* 📄 **[app.py](./app.py)** - The core Flask server, Meta WhatsApp Webhook handler, and the strict 7-Step Conversational Sales Funnel logic.
* 📄 **[gemini_scraper.py](./gemini_scraper.py)** - The Playwright automation script that handles persistent browser sessions, navigates the Gemini UI, injects the hybrid prompt, and captures the final output.
* 📄 **[requirements.txt](./requirements.txt)** - The list of Python libraries required for this project.

---

## 🚧 Main Challenges Faced & How I Solved Them

Building an end-to-end automation pipeline via UI scraping comes with unique edge cases. Here is how I architected solutions for the main roadblocks:

### 1. The "403 Forbidden" Google CDN Error
**Problem:** Initially, the script tried to download the generated image directly using its `src` URL. However, Google's CDN blocks unauthorized external requests with a 403 error.
**Solution:** I engineered a DOM-specific screenshotting method. Instead of downloading the URL, the Playwright script waits for the specific `model-response img` element to load and takes a high-res localized screenshot of just that element, entirely bypassing the CDN block.

### 2. The Playwright Concurrency Crash
**Problem:** When multiple users clicked the "Generate Poster" WhatsApp button simultaneously, the Flask server tried to open multiple Playwright instances on the same persistent user data directory, causing instant browser crashes.
**Solution:** Implemented a Python `threading.Lock()` mechanism in the Flask webhook. It acknowledges incoming Meta webhooks instantly (`200 OK`) but queues the actual browser scraping sequentially. Users wait silently, and the system never crashes.

### 3. AI Hallucinations & Irrelevant Backgrounds
**Problem:** A purely dynamic prompt caused the AI to generate generic corporate offices for categories like "Electronics" or "Graphic Design."
**Solution:** I developed a **Hybrid Prompt Architecture**. I created a master dictionary containing over 85+ business categories grouped with highly optimized, 25-word photorealistic scene descriptions. The script dynamically matches the user's input to the dictionary, ensuring a "Jeweller" gets a diamond display background while "Real Estate" gets a luxury 3D villa render.

### 4. Conversation State Overlap
**Problem:** During consecutive poster requests, Gemini would append the new prompt to the old chat, causing visual confusion and timeout errors.
**Solution:** Implemented a strict "State Reset" logic. Before every generation, the bot explicitly forces a navigation to a fresh chat URL (`https://gemini.google.com/app`), ensuring a clean slate and faster processing.

---

## 🏗️ System Architecture & User Flow
1. **Multi-Lingual Onboarding:** The bot dynamically adapts to Gujarati, Hindi, or English based on user preference.
2. **Sales Funnel:** A strict step-by-step flow collects business details (Category, Name, Number, Address) without overwhelming the user.
3. **Background Processing:** The Flask webhook triggers the locked Playwright scraper.
4. **Hybrid AI Prompting:** The script translates user details into a high-fidelity rendering command for Gemini.
5. **UI Automation:** The bot drives Chrome, generates the poster with embedded 3D typography, captures the DOM element, and delivers it to WhatsApp.

---

## 💻 Tech Stack & Tools
* **Backend:** Python, Flask
* **Browser Automation:** Playwright (Sync API)
* **AI Model:** Google Gemini (Nano Banana 2 / Imagen 3 via UI Scraping)
* **Integrations:** Meta WhatsApp Cloud API Webhooks
* **AI Coding Assistant:** Claude Code (for architectural guidance and rapid script refactoring)

---

## 🤝 Let's Connect
I am highly passionate about building robust AI agents, developing automated workflows, and solving complex automation challenges. 

If you're looking for an engineer who can architect, build, and deploy production-ready AI pipelines, let's talk!

**Ranjit Makvana**
*AI Automation Engineer*
