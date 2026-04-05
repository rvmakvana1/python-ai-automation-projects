# Python AI Automation Master Portfolio

Welcome to my central hub for **Advanced AI & Python Automation**. This repository showcases a collection of high-performance, autonomous systems designed to leverage **Artificial Intelligence (LLMs)** to solve real-world business challenges and streamline complex workflows.

---



# 🚀 WhatsApp-to-Gemini AI Automation Agency Bot


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



![WhatsApp Bot Flow & AI Posters](https://github.com/rvmakvana1/python-ai-automation-projects/blob/main/whatsapp%20automation.png?raw=true)

---

## 🤝 Let's Connect
I am highly passionate about building robust AI agents, developing automated workflows, and solving complex automation challenges. 

If you're looking for an engineer who can architect, build, and deploy production-ready AI pipelines, let's talk!

**Ranjit Makvana**
*AI Automation Engineer*
