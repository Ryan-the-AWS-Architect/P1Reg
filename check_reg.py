import hashlib
import json
import os
import re
from pathlib import Path

import requests
from bs4 import BeautifulSoup


WEBHOOK_URL = os.environ["DISCORD_WEBHOOK"]


HEADERS = {
    "User-Agent": "Mozilla/5.0 Registration Monitor",
}


SOURCES = {
    "P1S": {
        "url": "https://www.playeroneservices.com/registration",
        "state_file": Path("p1s_state.json"),
        "display_name_env": "STORE_P1S_NAME",
        "parser": "p1s",
    },
    "PGG": {
        "url": "https://www.gcpairodice.com/preorders-and-preregistrations",
        "state_file": Path("pgg_state.json"),
        "display_name_env": "STORE_PGG_NAME",
        "parser": "pgg",
    },
}


def clean_text(value):
    return re.sub(r"\s+", " ", value).strip()


def get_page(url):
    response = requests.get(
        url,
        headers=HEADERS,
        timeout=30,
    )

    response.raise_for_status()

    return response.text


def parse_p1s(html):
    """
    Parser for the existing registration page.
    """

    soup = BeautifulSoup(html, "html.parser")

    events = []

    for element in soup.find_all(["h2", "h3", "h4", "article"]):
        text = clean_text(element.get_text(" ", strip=True))

        if not text:
            continue

        if text.lower() in {
            "registration",
            "filters",
            "filter",
            "no results found",
        }:
            continue

        if re.search(
            r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s+\d{1,2}",
            text,
            re.IGNORECASE,
        ):
            events.append(text)

    return remove_duplicates(events)


def parse_pgg(html):
    """
    Parser for the PGG preorder/preregistration page.

    This intentionally uses a broader extraction strategy than P1S
    because the page has a different site structure.
    """

    soup = BeautifulSoup(html, "html.parser")

    events = []

    # Remove elements that generally contain navigation, scripts,
    # styling, or other content that should not be monitored.
    for element in soup(
        [
            "script",
            "style",
            "noscript",
            "svg",
            "header",
            "footer",
            "nav",
        ]
    ):
        element.decompose()

    # Look for common content containers.
    candidates = soup.find_all(
        [
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "article",
            "li",
            "p",
        ]
    )

    for element in candidates:
        text = clean_text(element.get_text(" ", strip=True))

        if not text:
            continue

        # Ignore extremely short navigation-like text.
        if len(text) < 4:
            continue

        # Ignore obvious generic page headings.
        if text.lower() in {
            "home",
            "contact",
            "about",
            "preorders",
            "preregistrations",
            "preorders and preregistrations",
            "menu",
            "search",
        }:
            continue

        # Ignore very long blocks. Those are usually entire sections
        # rather than individual listings.
        if len(text) > 500:
            continue

        events.append(text)

    events = remove_duplicates(events)

    return events


def remove_duplicates(items):
    unique_items = []
    seen = set()

    for item in items:
        if item not in seen:
            seen.add(item)
            unique_items.append(item)

    return unique_items


def parse_source(source_id, html):
    source = SOURCES[source_id]

    parser_name = source["parser"]

    if parser_name == "p1s":
        return parse_p1s(html)

    if parser_name == "pgg":
        return parse_pgg(html)

    raise ValueError(
        f"Unknown parser '{parser_name}' for source '{source_id}'."
    )


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


def load_previous_state(state_file):
    if not state_file.exists():
        return None

    try:
        return json.loads(
            state_file.read_text(encoding="utf-8")
        )

    except json.JSONDecodeError:
        print(
            f"Warning: Could not parse {state_file}. "
            "Treating this as a first run."
        )

        return None


def save_state(state_file, state):
    state_file.write_text(
        json.dumps(
            state,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def get_display_name(source_id, source):
    env_name = source["display_name_env"]

    display_name = os.environ.get(env_name, "").strip()

    if display_name:
        return display_name

    return source_id


def send_discord(message):
    response = requests.post(
        WEBHOOK_URL,
        json={
            "content": message,
            "allowed_mentions": {
                "parse": ["everyone", "roles"],
            },
        },
        timeout=30,
    )

    response.raise_for_status()


def send_test_message(source_id, source):
    display_name = get_display_name(source_id, source)

    message = (
        f"🧪 **{display_name} monitor test**\n\n"
        "Discord alerts are working correctly.\n\n"
        f"Source ID: `{source_id}`\n"
        f"Monitoring: {source['url']}"
    )

    send_discord(message)


def check_source(source_id, source, test_mode=False):
    display_name = get_display_name(source_id, source)

    print(f"Checking {source_id}: {source['url']}")

    html = get_page(source["url"])

    events = parse_source(
        source_id,
        html,
    )

    print(
        f"{source_id}: found {len(events)} monitored items."
    )

    current_state = get_state(events)

    if test_mode:
        send_test_message(
            source_id,
            source,
        )

        print(
            f"{source_id}: test message sent."
        )

        return

    previous_state = load_previous_state(
        source["state_file"]
    )

    if previous_state is None:
        save_state(
            source["state_file"],
            current_state,
        )

        print(
            f"{source_id}: baseline created. "
            "No alert sent."
        )

        return

    previous_events = set(
        previous_state.get("events", [])
    )

    new_events = [
        event
        for event in events
        if event not in previous_events
    ]

    if new_events:
        message = (
            f"🚨 **{display_name} UPDATE**\n\n"
            f"Source: `{source_id}`\n\n"
            "New listing detected:\n\n"
        )

        for event in new_events:
            message += f"• **{event}**\n"

        message += (
            f"\n🔗 {source['url']}"
        )

        send_discord(message)

        print(
            f"{source_id}: Discord alert sent "
            f"for {len(new_events)} new item(s)."
        )

    elif current_state["hash"] != previous_state.get("hash"):
        print(
            f"{source_id}: page changed, but no "
            "new listing was detected."
        )

    else:
        print(
            f"{source_id}: no changes detected."
        )

    save_state(
        source["state_file"],
        current_state,
    )


def main():
    test_mode = (
        os.environ.get(
            "TEST_MODE",
            "",
        ).lower()
        == "true"
    )

    for source_id, source in SOURCES.items():
        try:
            check_source(
                source_id,
                source,
                test_mode=test_mode,
            )

        except Exception as exc:
            print(
                f"ERROR checking {source_id}: {exc}"
            )

            # Continue checking the other sources.
            # A failure on one page should not prevent
            # the other page from being monitored.
            continue


if __name__ == "__main__":
    main()
