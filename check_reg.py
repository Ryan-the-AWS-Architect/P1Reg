import hashlib
import json
import os
import re
from pathlib import Path

import requests
from bs4 import BeautifulSoup

REGISTRATION_URL = "https://www.playeroneservices.com/registration"
WEBHOOK_URL = os.environ["DISCORD_WEBHOOK"]

STATE_FILE = Path("p1s_state.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0 P1S Registration Monitor"
}


def get_page():
    response = requests.get(
        REGISTRATION_URL,
        headers=HEADERS,
        timeout=30,
    )
    response.raise_for_status()
    return response.text


def clean_text(value):
    return re.sub(r"\s+", " ", value).strip()


def get_events(html):
    soup = BeautifulSoup(html, "html.parser")

    events = []

    # Squarespace pages generally expose event/product titles
    # as headings or links. We collect likely event blocks.
    for element in soup.find_all(["h2", "h3", "h4", "article"]):
        text = clean_text(element.get_text(" ", strip=True))

        if not text:
            continue

        # Ignore generic page headings.
        if text.lower() in {
            "registration",
            "filters",
            "filter",
            "no results found",
        }:
            continue

        # Event listings generally contain a date.
        if re.search(
            r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s+\d{1,2}",
            text,
            re.IGNORECASE,
        ):
            events.append(text)

    # Remove duplicates while preserving order.
    unique_events = []
    seen = set()

    for event in events:
        if event not in seen:
            seen.add(event)
            unique_events.append(event)

    return unique_events


def get_state(events):
    normalized = json.dumps(
        events,
        sort_keys=True,
        ensure_ascii=False,
    )

    return {
        "hash": hashlib.sha256(
            normalized.encode("utf-8")
        ).hexdigest(),
        "events": events,
    }


def send_discord(message):
    response = requests.post(
        WEBHOOK_URL,
        json={
            "content": message,
            "allowed_mentions": {
                "parse": ["everyone", "roles"]
            },
        },
        timeout=30,
    )

    response.raise_for_status()


def main():
    html = get_page()
    events = get_events(html)

    current_state = get_state(events)

    # TEST_MODE lets us verify Discord without waiting for a change.
    test_mode = os.environ.get("TEST_MODE", "").lower() == "true"

    if test_mode:
        send_discord(
            "🧪 **P1S registration monitor test**\n\n"
            "Discord alerts are working correctly.\n\n"
            f"Monitoring: {REGISTRATION_URL}"
        )

        print("P1S test message sent.")
        return

    previous_state = None

    if STATE_FILE.exists():
        try:
            previous_state = json.loads(
                STATE_FILE.read_text(encoding="utf-8")
            )
        except json.JSONDecodeError:
            previous_state = None

    if previous_state is None:
        # First run establishes the baseline.
        print("P1S baseline created. No alert sent.")

    elif current_state["hash"] != previous_state.get("hash"):
        old_events = set(previous_state.get("events", []))
        new_events = [
            event
            for event in events
            if event not in old_events
        ]

        if new_events:
            message = (
                "🚨 **P1S REGISTRATION UPDATE**\n\n"
                "New registration listing detected:\n\n"
            )

            for event in new_events:
                message += f"• **{event}**\n"

            message += (
                f"\n🔗 {REGISTRATION_URL}"
            )

            send_discord(message)
            print("P1S Discord alert sent.")

        else:
            print(
                "P1S page changed, but no new event listing "
                "was detected."
            )

    STATE_FILE.write_text(
        json.dumps(current_state, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
