# Gmail Cleaner

A simple interactive script to bulk-move emails from any Gmail label or category to Trash — useful for freeing up storage quickly.

## Requirements

- Python 3.9+
- [uv](https://docs.astral.sh/uv/) — handles dependencies automatically

Install uv if you don't have it:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## One-Time Google Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create or select a project
3. Search **"Gmail API"** → click **Enable**
4. Go to **APIs & Services → Credentials → Create Credentials → OAuth client ID**
   - Application type: **Desktop app**
5. Click **Download JSON** and move the file into this folder
6. Go to **APIs & Services → OAuth consent screen → Test users**
   - Add your Gmail address (required while the app is in Testing mode)

## Usage

```bash
uv run gmail_cleaner.py
```

On first run a browser window opens for Google sign-in. Your session is saved to `token.json` so subsequent runs skip the login step.

**Example session:**

```
Authenticating with Gmail...
Fetching labels...

=== Gmail Labels ===

  Gmail Categories
  ────────────────
    1.  Social
    2.  Promotions
    3.  Updates
    4.  Forums

  System Labels
  ─────────────
    5.  Inbox
    6.  Sent
    ...

Enter label number (or label name): 2

Counting emails in 'Promotions'...
Found 4,312 email(s) in 'Promotions'.
Move all 4312 to Trash? [y/N] y

Fetching message IDs and moving to Trash...
  Trashed 4312/4312 emails...

Done. 4312 email(s) moved to Trash.
They will be permanently deleted after 30 days (or empty Trash manually).
```

## Security Notes

- `client_secret_*.json` and `token.json` are gitignored and should never be committed
- The script requests only the `gmail.modify` scope (no read access to email content)
- OAuth credentials stay on your machine only
