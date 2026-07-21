from flask import Flask
from webhook import webhook_bp
from scheduler import start_scheduler
from sheets import ensure_header_row

def create_app() -> Flask:
    """Create and configure the Flask application.

    Registers the webhook blueprint and initializes supporting services.
    """
    app = Flask(__name__)

    # Register the /webhook routes
    app.register_blueprint(webhook_bp)

    return app


if __name__ == "__main__":
    print("=" * 50)
    print("  PromoPe Bot is running!")
    print("=" * 50)

    # Ensure Google Sheet has a header row (safe to call every startup)
    try:
        ensure_header_row()
    except Exception as e:
        print(f"[Main] Could not verify sheet header (check credentials): {e}")

    # Start background scheduler (morning / midday / evening jobs)
    start_scheduler()

    # Create and run Flask app on port 5000
    app = create_app()
    app.run(host="0.0.0.0", port=5000, debug=False)
