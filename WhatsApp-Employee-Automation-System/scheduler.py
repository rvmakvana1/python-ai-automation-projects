from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from whatsapp import send_message
from config import EMPLOYEES

# The single APScheduler instance used by the whole app
scheduler = BackgroundScheduler(timezone="Asia/Kolkata")

# --- Message Templates ---

def _morning_message(name: str) -> str:
    """Return the daily morning motivation + task message for an employee."""
    return (
        f"Good Morning {name}! 👋\n\n"
        "Aaj ke tasks:\n"
        "✅ Brands dhundho - LinkedIn, Instagram, Facebook pe\n"
        "✅ Influencers find karo aur connect karo\n"
        "✅ Sab ko message karo\n\n"
        "📸 Shaam 6 baje apni report screenshots ke saath bhejo!\n\n"
        "All the best! 💪"
    )


def _midday_reminder(name: str) -> str:
    """Return the midday check-in reminder message."""
    return f"Hey {name}! Kaam kaisa chal raha hai? 💪 Koi help chahiye?"


def _evening_report_request() -> str:
    """Return the standardized evening report request message."""
    return (
        "Shaam ki report time! Please yeh sab batao:\n\n"
        "1. Aaj kitni Brands dekhi? Aur kahan? (LinkedIn/Instagram/Facebook)\n"
        "2. Kitni Brands ko message kiya?\n"
        "3. Kitne Brands ka reply aaya?\n"
        "4. Kitne Influencers find kiye? Aur kahan?\n"
        "5. Kitne Influencers ko message kiya?\n"
        "6. Kitne Influencers ka reply aaya?\n\n"
        "Screenshot bhi bhejo!"
    )


# --- Scheduled Job Functions ---

def send_morning_messages():
    """10:00 AM job — send the morning task reminder to every employee."""
    print("[Scheduler] Sending morning messages...")
    for emp in EMPLOYEES:
        send_message(emp["phone"], _morning_message(emp["name"]))


def send_midday_reminders():
    """12:30 PM job — send the midday check-in to every employee."""
    print("[Scheduler] Sending midday reminders...")
    for emp in EMPLOYEES:
        send_message(emp["phone"], _midday_reminder(emp["name"]))


def send_evening_report_requests():
    """6:00 PM job — ask every employee to submit their evening report."""
    import state  # imported here to avoid circular imports at module level
    print("[Scheduler] Sending evening report requests...")
    for emp in EMPLOYEES:
        send_message(emp["phone"], _evening_report_request())
        # Move each employee to the 'evening_started' step so the webhook
        # knows to expect a report reply from them.
        state.set_step(emp["phone"], "evening_started")


# --- Scheduler Initializer ---

def start_scheduler():
    """Register all cron jobs and start the background scheduler.

    Call this once during app startup (from main.py).
    All times are in IST (Asia/Kolkata).
    """
    # 10:00 AM — Morning motivation
    scheduler.add_job(
        send_morning_messages,
        CronTrigger(hour=10, minute=0),
        id="morning_messages",
        replace_existing=True,
    )

    # 12:30 PM — Midday check-in
    scheduler.add_job(
        send_midday_reminders,
        CronTrigger(hour=12, minute=30),
        id="midday_reminders",
        replace_existing=True,
    )

    # 6:00 PM — Evening report request
    scheduler.add_job(
        send_evening_report_requests,
        CronTrigger(hour=18, minute=0),
        id="evening_reports",
        replace_existing=True,
    )

    scheduler.start()
    print("[Scheduler] APScheduler started with 3 daily jobs (IST)")
