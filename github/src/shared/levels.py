"""
How powerful a computer is, in the words people use when they buy one, and
how many tabs each level keeps open.

Shared by the installer and the taskbar. /usr/lib/onlybrowseros/tune uses
the same memory thresholds, and the browser settings page keeps a copy in
src/firefox/tablimit/settings.js: change all three together.

What gets saved (tabs.conf) is "auto" when the recommended level is chosen,
so the choice follows a memory upgrade, and a number otherwise.
"""

ORDER = ["low", "mid", "high"]

LEVELS = {
    "low": ("Low-end PC", "Older or budget computer"),
    "mid": ("Mid-range PC", "Everyday computer"),
    "high": ("High-end PC", "Fast, newer computer"),
}


def recommended_tabs(mb):
    # MemTotal reads below the RAM on the sticker, so each threshold sits
    # between two common sizes.
    if mb < 1500:
        return 1
    if mb < 3000:
        return 2
    if mb < 6500:
        return 4
    return 8


def recommended_level(mb):
    if mb < 3000:
        return "low"
    if mb < 6500:
        return "mid"
    return "high"


def tabs_for(level, mb):
    if level == "low":
        return 1 if mb < 1500 else 2
    return 4 if level == "mid" else 8


def setting_for(level, mb):
    """The value for set-tab-limit / tabs.conf."""
    return "auto" if level == recommended_level(mb) else str(tabs_for(level, mb))


def level_for(limit, automatic, mb):
    """Which level a saved setting belongs to."""
    if automatic:
        return recommended_level(mb)
    if limit <= 2:
        return "low"
    return "mid" if limit <= 4 else "high"


def tabs_text(n):
    return f"up to {n} tab{'' if n == 1 else 's'}"
