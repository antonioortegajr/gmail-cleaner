#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = [
#   "google-api-python-client>=2.100.0",
#   "google-auth-oauthlib>=1.1.0",
#   "google-auth-httplib2>=0.1.1",
# ]
# ///
"""
Gmail Cleaner — Move emails from a label/category to Trash in bulk.

=== ONE-TIME SETUP ===
1. Install uv (if not already installed):
   curl -LsSf https://astral.sh/uv/install.sh | sh

2. Go to https://console.cloud.google.com
3. Create a new project (or select an existing one)
4. Enable the Gmail API:
   - In the search bar, search "Gmail API" → click Enable
5. Create OAuth 2.0 credentials:
   - Go to APIs & Services → Credentials → Create Credentials → OAuth client ID
   - Application type: Desktop app
   - Download the JSON file and move it to the same folder as this script
6. Run the script (uv handles dependencies automatically):
   uv run gmail_cleaner.py

On first run, a browser window will open asking you to authorize Gmail access.
Your login is saved to "token.json" — subsequent runs won't need re-authorization.

Keep credentials.json and token.json private (don't commit them to git).
"""

import glob
import os
import sys

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Scopes required: modify lets us trash emails
SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]

TOKEN_FILE = "token.json"

# Google names the downloaded file "client_secret_<id>.json" or "credentials.json"
_CREDENTIALS_CANDIDATES = glob.glob("client_secret_*.json") + ["credentials.json"]
CREDENTIALS_FILE = next((f for f in _CREDENTIALS_CANDIDATES if os.path.exists(f)), None)

# Human-readable names for Gmail's built-in label IDs
SYSTEM_LABEL_NAMES = {
    "INBOX": "Inbox",
    "SENT": "Sent",
    "DRAFT": "Drafts",
    "SPAM": "Spam",
    "TRASH": "Trash",
    "STARRED": "Starred",
    "IMPORTANT": "Important",
    "UNREAD": "Unread",
    "CATEGORY_SOCIAL": "Social",
    "CATEGORY_PROMOTIONS": "Promotions",
    "CATEGORY_UPDATES": "Updates",
    "CATEGORY_FORUMS": "Forums",
    "CATEGORY_PERSONAL": "Personal",
}

# Labels we should never trash (destructive or pointless)
SKIP_LABELS = {"TRASH", "DRAFT"}


def authenticate():
    """Run OAuth2 flow and return an authorized Gmail API service."""
    if not CREDENTIALS_FILE:
        print("""
Error: No credentials file found in the current directory.
Complete these one-time steps:

  1. Go to https://console.cloud.google.com
  2. Create or select a project
  3. Search "Gmail API" → Enable it
  4. Go to APIs & Services → Credentials → Create Credentials → OAuth client ID
     - Application type: Desktop app
  5. Click "Download JSON" and move the file to the same folder as this script
  6. In the Google Cloud Console, go to APIs & Services → OAuth consent screen
     → Test users → Add your Gmail address (required while app is in Testing mode)

Then run this script again.
""")
        sys.exit(1)

    creds = None

    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w") as token:
            token.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def fetch_labels(service):
    """Return list of label dicts, excluding labels we should skip."""
    result = service.users().labels().list(userId="me").execute()
    labels = result.get("labels", [])
    return [lb for lb in labels if lb["id"] not in SKIP_LABELS]


def display_labels(labels):
    """
    Print a numbered menu of labels grouped into:
      - Gmail Categories
      - System Labels
      - Your Labels (user-created)
    Returns the ordered list so selection by index works.
    """
    categories = []
    system = []
    user = []

    for lb in labels:
        lid = lb["id"]
        if lid.startswith("CATEGORY_"):
            categories.append(lb)
        elif lb.get("type") == "system":
            system.append(lb)
        else:
            user.append(lb)

    ordered = []

    def print_group(title, group):
        if not group:
            return
        print(f"\n  {title}")
        print(f"  {'─' * len(title)}")
        for lb in group:
            idx = len(ordered) + 1
            name = SYSTEM_LABEL_NAMES.get(lb["id"], lb["name"])
            print(f"  {idx:>3}.  {name}")
            ordered.append(lb)

    print("\n=== Gmail Labels ===")
    print_group("Gmail Categories", categories)
    print_group("System Labels", system)
    print_group("Your Labels", user)
    print()

    return ordered


def count_messages(service, label_id):
    """Return the total number of messages with the given label."""
    total = 0
    page_token = None
    while True:
        kwargs = {"userId": "me", "labelIds": [label_id], "maxResults": 500}
        if page_token:
            kwargs["pageToken"] = page_token
        response = service.users().messages().list(**kwargs).execute()
        messages = response.get("messages", [])
        total += len(messages)
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    return total


def fetch_all_message_ids(service, label_id):
    """Yield message IDs for all messages with the given label."""
    page_token = None
    while True:
        kwargs = {"userId": "me", "labelIds": [label_id], "maxResults": 500}
        if page_token:
            kwargs["pageToken"] = page_token
        response = service.users().messages().list(**kwargs).execute()
        for msg in response.get("messages", []):
            yield msg["id"]
        page_token = response.get("nextPageToken")
        if not page_token:
            break


def batch_trash(service, message_ids):
    """
    Move messages to Trash in batches of 1000 (Gmail API limit).
    Returns the total number of messages trashed.
    """
    ids = list(message_ids)
    total = len(ids)
    trashed = 0
    batch_size = 1000

    for start in range(0, total, batch_size):
        chunk = ids[start : start + batch_size]
        service.users().messages().batchModify(
            userId="me",
            body={
                "ids": chunk,
                "addLabelIds": ["TRASH"],
                "removeLabelIds": ["INBOX"],
            },
        ).execute()
        trashed += len(chunk)
        print(f"  Trashed {trashed}/{total} emails...", end="\r")

    print()  # newline after the progress line
    return trashed


def pick_label(ordered_labels):
    """Prompt the user to select a label by number or name. Returns the label dict."""
    while True:
        raw = input("Enter label number (or label name): ").strip()
        if not raw:
            continue

        # Try numeric selection
        if raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(ordered_labels):
                return ordered_labels[idx]
            print(f"  Please enter a number between 1 and {len(ordered_labels)}.")
            continue

        # Try name match (case-insensitive, check both API ID and display name)
        raw_lower = raw.lower()
        matches = [
            lb for lb in ordered_labels
            if raw_lower in lb["name"].lower()
            or raw_lower in SYSTEM_LABEL_NAMES.get(lb["id"], "").lower()
        ]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            names = ", ".join(
                SYSTEM_LABEL_NAMES.get(lb["id"], lb["name"]) for lb in matches
            )
            print(f"  Multiple matches: {names}. Be more specific.")
            continue

        print("  No label found. Try the number from the list above.")


def main():
    print("Authenticating with Gmail...")
    try:
        service = authenticate()
    except Exception as e:
        print(f"Authentication failed: {e}")
        sys.exit(1)

    print("Fetching labels...")
    try:
        labels = fetch_labels(service)
    except HttpError as e:
        print(f"Failed to fetch labels: {e}")
        sys.exit(1)

    if not labels:
        print("No labels found in your account.")
        sys.exit(0)

    ordered_labels = display_labels(labels)

    selected = pick_label(ordered_labels)
    label_name = SYSTEM_LABEL_NAMES.get(selected["id"], selected["name"])

    print(f"\nCounting emails in '{label_name}'...")
    try:
        count = count_messages(service, selected["id"])
    except HttpError as e:
        print(f"Failed to count messages: {e}")
        sys.exit(1)

    if count == 0:
        print("No emails found in that label. Nothing to do.")
        sys.exit(0)

    print(f"Found {count} email(s) in '{label_name}'.")
    confirm = input(f"Move all {count} to Trash? [y/N] ").strip().lower()
    if confirm != "y":
        print("Aborted — no emails were moved.")
        sys.exit(0)

    print(f"Fetching message IDs and moving to Trash...")
    try:
        ids = list(fetch_all_message_ids(service, selected["id"]))
        trashed = batch_trash(service, ids)
    except HttpError as e:
        print(f"Error during trash operation: {e}")
        sys.exit(1)

    print(f"\nDone. {trashed} email(s) moved to Trash.")
    print("They will be permanently deleted after 30 days (or empty Trash manually).")


if __name__ == "__main__":
    main()
