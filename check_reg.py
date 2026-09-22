import hashlib
import json
import os
import re
from pathlib import Path

import requests
from bs4 import BeautifulSoup


WEBHOOK_URL = os.environ["DISCORD_WEBHOOK"]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    )
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


def truncate_text(text, max_length):
    text = clean_text(text)

    if len(text) <= max_length:
        return text

    return text[: max_length - 1].rstrip() + "…"


def get_page(url):
    response = requests.get(
        url,
        headers=HEADERS,
        timeout=30,
    )

    response.raise_for_status()

    return response.text


# ---------------------------------------------------------------------------
# P1S PARSER
# ---------------------------------------------------------------------------

def parse_p1s(html):
    """
    Parse Player One Services registration listings.
    """

    soup = BeautifulSoup(html, "html.parser")

    events = []

    date_pattern = re.compile(
        r"\b("
        r"Jan(?:uary)?|"
        r"Feb(?:ruary)?|"
        r"Mar(?:ch)?|"
        r"Apr(?:il)?|"
        r"May|"
        r"Jun(?:e)?|"
        r"Jul(?:y)?|"
        r"Aug(?:ust)?|"
        r"Sep(?:t(?:ember)?)?|"
        r"Oct(?:ober)?|"
        r"Nov(?:ember)?|"
        r"Dec(?:ember)?"
        r")\.?\s+\d{1,2}(?:st|nd|rd|th)?",
        re.IGNORECASE,
    )

    candidates = soup.find_all(
        ["article", "h2", "h3", "h4"]
    )

    for element in candidates:
        text = clean_text(
            element.get_text(
                " ",
                strip=True,
            )
        )

        if not text:
            continue

        if not date_pattern.search(text):
            continue

        lower_text = text.lower()

        if "no results found" in lower_text:
            continue

        if "no results match your search" in lower_text:
            continue

        if "clear filters" in lower_text:
            continue

        text = re.sub(
            r"^registration\s+",
            "",
            text,
            flags=re.IGNORECASE,
        )

        # Remove duplicate filter/navigation text if it occurs inside
        # the scraped element.
        text = re.sub(
            r"registration\s+registration\s+",
            "Registration ",
            text,
            flags=re.IGNORECASE,
        )

        event_match = re.match(
            r"^(?P<date>.+?)\s*-\s*(?P<title>.+?)(?:\s+(?P<body>Secure your registration.*))?$",
            text,
            flags=re.IGNORECASE,
        )

        if event_match:
            date = clean_text(
                event_match.group("date")
            )

            title = clean_text(
                event_match.group("title")
            )

            body = clean_text(
                event_match.group("body") or ""
            )

        else:
            date_match = date_pattern.search(text)

            if not date_match:
                continue

            date = clean_text(
                date_match.group(0)
            )

            remainder = clean_text(
                text[date_match.end():]
            )

            title = remainder
            body = ""

        price_match = re.search(
            r"\$\d+(?:\.\d{2})?",
            text,
        )

        price = (
            price_match.group(0)
            if price_match
            else None
        )

        if price:
            body = clean_text(
                body.replace(price, "")
            )

        event = {
            "date": date,
            "title": title,
            "description": truncate_text(
                body,
                300,
            ),
            "price": price,
        }

        if event not in events:
            events.append(event)

    return events


# ---------------------------------------------------------------------------
# PGG PARSER
# ---------------------------------------------------------------------------

def parse_pgg(html):
    """
    Initial parser for the Paradise Games & Gifts page.

    PGG uses a different page structure from P1S, so it has its own parser.
    """

    soup = BeautifulSoup(html, "html.parser")

    for element in soup.find_all(
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

    events = []

    headings = soup.find_all(
        [
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
        ]
    )

    for heading in headings:
        title = clean_text(
            heading.get_text(
                " ",
                strip=True,
            )
        )

        if not title:
            continue

        lower_title = title.lower()

        if lower_title in {
            "home",
            "about",
            "contact",
            "menu",
            "search",
            "preorders",
            "preregistrations",
            "preorders and preregistrations",
        }:
            continue

        if len(title) < 4:
            continue

        description = ""

        sibling = heading.find_next_sibling()

        if sibling:
            description = clean_text(
                sibling.get_text(
                    " ",
                    strip=True,
                )
            )

        price_match = re.search(
            r"\$\d+(?:\.\d{2})?",
            title + " " + description,
        )

        price = (
            price_match.group(0)
            if price_match
            else None
        )

        events.append(
            {
                "date": None,
                "title": title,
                "description": truncate_text(
                    description,
                    300,
                ),
                "price": price,
            }
        )

    return remove_duplicate_events(events)


# ---------------------------------------------------------------------------
# PARSER ROUTER
# ---------------------------------------------------------------------------

def parse_source(source_id, html):
    source = SOURCES[source_id]

    parser_name = source["parser"]

    if parser_name == "p1s":
        return parse_p1s(html)

    if parser_name == "pgg":
        return parse_pgg(html)

    raise ValueError(
        f"Unknown parser '{parser_name}' "
        f"for source '{source_id}'."
    )


# ---------------------------------------------------------------------------
# STATE
# ---------------------------------------------------------------------------

def normalize_event(event):
    return {
        "date": clean_text(
            event.get("date") or ""
        ),
        "title": clean_text(
            event.get("title") or ""
        ),
        "description": clean_text(
            event.get("description") or ""
        ),
        "price": event.get("price"),
    }


def get_state(events):
    normalized_events = [
        normalize_event(event)
        for event in events
    ]

    normalized_events = sorted(
        normalized_events,
        key=lambda event: (
            event.get("date") or "",
            event.get("title") or "",
        ),
    )

    serialized = json.dumps(
        normalized_events,
        sort_keys=True,
        ensure_ascii=False,
    )

    return {
        "hash": hashlib.sha256(
            serialized.encode("utf-8")
        ).hexdigest(),
        "events": normalized_events,
    }


def load_previous_state(state_file):
    if not state_file.exists():
        return None

    try:
        return json.loads(
            state_file.read_text(
                encoding="utf-8"
            )
        )

    except json.JSONDecodeError:
        print(
            f"WARNING: Could not parse {state_file}. "
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


# ---------------------------------------------------------------------------
# DISCORD
# ---------------------------------------------------------------------------

def get_display_name(source_id, source):
    """
    Human-readable names are supplied through GitHub Secrets.
    They are deliberately not stored in the public repository.
    """

    env_name = source["display_name_env"]

    display_name = os.environ.get(
        env_name,
        "",
    ).strip()

    if display_name:
        return display_name

    return source_id


def send_discord_embed(
    source_id,
    source,
    new_events,
):
    display_name = get_display_name(
        source_id,
        source,
    )

    fields = []

    for event in new_events[:25]:
        date = event.get("date")
        title = event.get("title")
        description = event.get("description")
        price = event.get("price")

        heading_parts = []

        if date:
            heading_parts.append(date)

        if title:
            heading_parts.append(title)

        heading = " — ".join(
            heading_parts
        )

        if not heading:
            heading = "New Listing"

        value_parts = []

        if description:
            value_parts.append(
                description
            )

        if price:
            value_parts.append(
                f"💵 **{price}**"
            )

        value = "\n".join(
            value_parts
        )

        if not value:
            value = "New listing detected."

        fields.append(
            {
                "name": heading[:256],
                "value": value[:1024],
                "inline": False,
            }
        )

    payload = {
        "embeds": [
            {
                "title": (
                    f"🚨 {source_id} "
                    "REGISTRATION UPDATE"
                ),
                "description": (
                    f"**{display_name}**\n\n"
                    "New registration listing detected."
                ),
                "color": 15158332,
                "fields": fields,
                "footer": {
                    "text": f"Source: {source_id}"
                },
                "url": source["url"],
            }
        ],
        "allowed_mentions": {
            "parse": [],
        },
    }

    response = requests.post(
        WEBHOOK_URL,
        json=payload,
        timeout=30,
    )

    response.raise_for_status()


def send_test_message(
    source_id,
    source,
):
    display_name = get_display_name(
        source_id,
        source,
    )

    payload = {
        "embeds": [
            {
                "title": (
                    f"🧪 {source_id} "
                    "MONITOR TEST"
                ),
                "description": (
                    f"**{display_name}**\n\n"
                    "Discord alerts are working correctly."
                ),
                "color": 3447003,
                "fields": [
                    {
                        "name": "Source",
                        "value": f"`{source_id}`",
                        "inline": True,
                    },
                    {
                        "name": "URL",
                        "value": source["url"],
                        "inline": False,
                    },
                ],
            }
        ],
        "allowed_mentions": {
            "parse": [],
        },
    }

    response = requests.post(
        WEBHOOK_URL,
        json=payload,
        timeout=30,
    )

    response.raise_for_status()


# ---------------------------------------------------------------------------
# COMPARISON
# ---------------------------------------------------------------------------

def event_key(event):
    normalized = normalize_event(event)

    return json.dumps(
        normalized,
        sort_keys=True,
        ensure_ascii=False,
    )


def find_new_events(
    previous_events,
    current_events,
):
    previous_keys = {
        event_key(event)
        for event in previous_events
    }

    return [
        event
        for event in current_events
        if event_key(event)
        not in previous_keys
    ]


def remove_duplicate_events(events):
    unique = []
    seen = set()

    for event in events:
        key = event_key(event)

        if key in seen:
            continue

        seen.add(key)
        unique.append(event)

    return unique


# ---------------------------------------------------------------------------
# CHECKING
# ---------------------------------------------------------------------------

def check_source(
    source_id,
    source,
    test_mode=False,
):
    print(
        f"Checking {source_id}: "
        f"{source['url']}"
    )

    html = get_page(
        source["url"]
    )

    events = parse_source(
        source_id,
        html,
    )

    print(
        f"{source_id}: found "
        f"{len(events)} monitored item(s)."
    )

    # Print parsed events to the Actions log.
    # Useful for tuning the PGG parser.
    for event in events:
        print(
            "  - "
            f"{event.get('date') or ''} "
            f"{event.get('title') or ''} "
            f"{event.get('price') or ''}"
        )

    current_state = get_state(
        events
    )

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

    # First run creates a baseline.
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

    previous_events = previous_state.get(
        "events",
        [],
    )

    new_events = find_new_events(
        previous_events,
        events,
    )

    if new_events:
        send_discord_embed(
            source_id,
            source,
            new_events,
        )

        print(
            f"{source_id}: sent Discord alert "
            f"for {len(new_events)} new item(s)."
        )

    elif (
        current_state["hash"]
        != previous_state.get("hash")
    ):
        print(
            f"{source_id}: page changed, "
            "but no new listing was detected."
        )

    else:
        print(
            f"{source_id}: no changes detected."
        )

    save_state(
        source["state_file"],
        current_state,
    )


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

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
                f"ERROR checking "
                f"{source_id}: {exc}"
            )

            # A failure on one source should not
            # prevent the other source from running.
            continue


if __name__ == "__main__":
    main()
