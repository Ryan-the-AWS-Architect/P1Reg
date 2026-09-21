import os
import re
import requests
from bs4 import BeautifulSoup

URL = "https://www.playeroneservices.com/registration"
WEBHOOK = os.environ["DISCORD_WEBHOOK"]

response = requests.get(
    URL,
    headers={
        "User-Agent": "Mozilla/5.0 Player1RegistrationMonitor"
    },
    timeout=30,
)

response.raise_for_status()

soup = BeautifulSoup(response.text, "html.parser")

# Get the visible text from the registration page.
text = soup.get_text(" ", strip=True)

# Look for registration-related content.
registration_keywords = [
    "register",
    "registration",
    "secure your registration",
]

found = []

for keyword in registration_keywords:
    if keyword.lower() in text.lower():
        found.append(keyword)

# Save a simplified representation of the page.
state = re.sub(r"\s+", " ", text).strip()

# GitHub Actions provides this file between runs.
state_file = "previous_state.txt"

previous = ""

if os.path.exists(state_file):
    with open(state_file, "r", encoding="utf-8") as f:
        previous = f.read()

# Only alert when the page has changed.
if previous and state != previous:
    message = (
        "🚨 **P1S registration page changed!**\n\n"
        f"{URL}\n\n"
        "Check the registration page for newly opened events."
    )

    result = requests.post(
        WEBHOOK,
        json={
            "content": message
        },
        timeout=30,
    )

    result.raise_for_status()

with open(state_file, "w", encoding="utf-8") as f:
    f.write(state)
