import time


try:
    import winsound
except ImportError:
    winsound = None


PATTERNS = {
    "program-start": [("tone", 880, 80), ("gap", 0, 60), ("tone", 1040, 80), ("gap", 0, 60), ("tone", 1240, 80)],
    "program-close": [("tone", 660, 90), ("gap", 0, 70), ("tone", 520, 90), ("gap", 0, 70), ("tone", 440, 120)],
    "open-design": [("tone", 620, 80)],
    "crop-start": [("tone", 420, 70), ("gap", 0, 50), ("tone", 420, 70), ("gap", 0, 50), ("tone", 420, 70)],
    "crop-complete": [("tone", 880, 70), ("gap", 0, 50), ("tone", 1040, 70)],
    "crop-error": [("tone", 240, 90), ("gap", 0, 30), ("tone", 160, 140)],
    "delete-design": [("tone", 260, 30), ("gap", 0, 20), ("tone", 240, 30), ("gap", 0, 20), ("tone", 220, 30), ("gap", 0, 20), ("tone", 200, 40)],
    "window-close": [("tone", 560, 70), ("gap", 0, 50), ("tone", 760, 100)],
}


def play_event_pattern(event_name, enabled=True):
    if not enabled or winsound is None:
        return False
    for kind, frequency, duration in PATTERNS.get(event_name, []):
        if kind == "tone":
            winsound.Beep(frequency, duration)
        else:
            time.sleep(duration / 1000)
    return True

