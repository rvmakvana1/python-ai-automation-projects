# In-memory conversation state store for all employees.
# Persists only while the server is running; replace with a DB for production.

# Structure: { phone: { "step": str, "data": dict } }
_state = {}

# --- Valid Steps ---
# idle           → No active conversation
# evening_started → Evening report message was sent, waiting for text reply
# waiting_screenshot → Text reply received, waiting for screenshot image
# done           → Report fully submitted and saved

def get_state(phone: str) -> dict:
    """Return the full state dict for a given phone number.
    Creates a fresh idle state if employee is not yet tracked."""
    if phone not in _state:
        _state[phone] = {"step": "idle", "data": {}}
    return _state[phone]


def set_step(phone: str, step: str) -> None:
    """Update the current conversation step for an employee."""
    get_state(phone)          # ensure entry exists
    _state[phone]["step"] = step
    print(f"[State] {phone} → step set to '{step}'")


def save_data(phone: str, key: str, value) -> None:
    """Store a single key-value pair in an employee's collected data."""
    get_state(phone)          # ensure entry exists
    _state[phone]["data"][key] = value
    print(f"[State] {phone} → saved data key='{key}'")


def get_data(phone: str) -> dict:
    """Return all collected data for an employee."""
    return get_state(phone).get("data", {})


def reset_state(phone: str) -> None:
    """Clear all state for an employee after their report has been saved."""
    _state[phone] = {"step": "idle", "data": {}}
    print(f"[State] {phone} → state reset to idle")
