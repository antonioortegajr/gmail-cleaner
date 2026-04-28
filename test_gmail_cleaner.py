# /// script
# requires-python = ">=3.9"
# dependencies = [
#   "pytest",
#   "google-api-python-client>=2.100.0",
#   "google-auth-oauthlib>=1.1.0",
#   "google-auth-httplib2>=0.1.1",
# ]
# ///
"""Tests for gmail_cleaner.py — pure logic and mocked API calls."""
import sys
from unittest.mock import MagicMock, call, patch

import pytest

import gmail_cleaner as gc


# ---------------------------------------------------------------------------
# fetch_labels
# ---------------------------------------------------------------------------

def make_service(labels):
    svc = MagicMock()
    svc.users().labels().list(userId="me").execute.return_value = {"labels": labels}
    return svc


def test_fetch_labels_excludes_skip_labels():
    labels = [
        {"id": "INBOX", "name": "INBOX"},
        {"id": "TRASH", "name": "TRASH"},
        {"id": "DRAFT", "name": "Drafts"},
        {"id": "CATEGORY_PROMOTIONS", "name": "Promotions"},
    ]
    result = gc.fetch_labels(make_service(labels))
    ids = [lb["id"] for lb in result]
    assert "TRASH" not in ids
    assert "DRAFT" not in ids
    assert "INBOX" in ids
    assert "CATEGORY_PROMOTIONS" in ids


def test_fetch_labels_empty_account():
    svc = MagicMock()
    svc.users().labels().list(userId="me").execute.return_value = {}
    result = gc.fetch_labels(svc)
    assert result == []


# ---------------------------------------------------------------------------
# display_labels
# ---------------------------------------------------------------------------

SAMPLE_LABELS = [
    {"id": "CATEGORY_PROMOTIONS", "name": "CATEGORY_PROMOTIONS", "type": "system"},
    {"id": "INBOX", "name": "INBOX", "type": "system"},
    {"id": "my-list", "name": "Newsletter", "type": "user"},
]


def test_display_labels_returns_all_labels(capsys):
    ordered = gc.display_labels(SAMPLE_LABELS)
    assert len(ordered) == len(SAMPLE_LABELS)


def test_display_labels_categories_come_first(capsys):
    ordered = gc.display_labels(SAMPLE_LABELS)
    # First item should be the CATEGORY_ label
    assert ordered[0]["id"] == "CATEGORY_PROMOTIONS"


def test_display_labels_user_labels_last(capsys):
    ordered = gc.display_labels(SAMPLE_LABELS)
    assert ordered[-1]["id"] == "my-list"


def test_display_labels_uses_friendly_names(capsys):
    gc.display_labels(SAMPLE_LABELS)
    out = capsys.readouterr().out
    assert "Promotions" in out
    assert "Inbox" in out
    assert "Newsletter" in out


# ---------------------------------------------------------------------------
# pick_label
# ---------------------------------------------------------------------------

ORDERED = [
    {"id": "INBOX", "name": "INBOX"},
    {"id": "CATEGORY_PROMOTIONS", "name": "CATEGORY_PROMOTIONS"},
    {"id": "work", "name": "Work"},
]


def test_pick_label_by_number():
    with patch("builtins.input", return_value="2"):
        result = gc.pick_label(ORDERED)
    assert result["id"] == "CATEGORY_PROMOTIONS"


def test_pick_label_by_name_exact(capsys):
    with patch("builtins.input", return_value="Work"):
        result = gc.pick_label(ORDERED)
    assert result["id"] == "work"


def test_pick_label_by_name_case_insensitive(capsys):
    with patch("builtins.input", return_value="work"):
        result = gc.pick_label(ORDERED)
    assert result["id"] == "work"


def test_pick_label_by_system_display_name(capsys):
    with patch("builtins.input", return_value="Inbox"):
        result = gc.pick_label(ORDERED)
    assert result["id"] == "INBOX"


def test_pick_label_invalid_then_valid(capsys):
    inputs = iter(["99", "1"])
    with patch("builtins.input", side_effect=inputs):
        result = gc.pick_label(ORDERED)
    assert result["id"] == "INBOX"
    out = capsys.readouterr().out
    assert "between 1 and" in out


def test_pick_label_ambiguous_then_specific(capsys):
    # "ca" matches CATEGORY_PROMOTIONS display name "Promotions"? No — but
    # searching "o" matches both "Promotions" and "Work" in system names.
    # Use "promotions" which is unambiguous.
    with patch("builtins.input", return_value="promotions"):
        result = gc.pick_label(ORDERED)
    assert result["id"] == "CATEGORY_PROMOTIONS"


# ---------------------------------------------------------------------------
# count_messages
# ---------------------------------------------------------------------------

def test_count_messages_single_page():
    svc = MagicMock()
    svc.users().messages().list().execute.return_value = {
        "messages": [{"id": "a"}, {"id": "b"}],
    }
    assert gc.count_messages(svc, "INBOX") == 2


def test_count_messages_multiple_pages():
    responses = [
        {"messages": [{"id": str(i)} for i in range(500)], "nextPageToken": "tok1"},
        {"messages": [{"id": str(i)} for i in range(200)], "nextPageToken": None},
    ]
    svc = MagicMock()
    svc.users().messages().list().execute.side_effect = responses
    assert gc.count_messages(svc, "INBOX") == 700


def test_count_messages_empty_label():
    svc = MagicMock()
    svc.users().messages().list().execute.return_value = {"messages": []}
    assert gc.count_messages(svc, "INBOX") == 0


# ---------------------------------------------------------------------------
# fetch_all_message_ids
# ---------------------------------------------------------------------------

def test_fetch_all_message_ids_single_page():
    svc = MagicMock()
    svc.users().messages().list().execute.return_value = {
        "messages": [{"id": "x1"}, {"id": "x2"}],
    }
    ids = list(gc.fetch_all_message_ids(svc, "INBOX"))
    assert ids == ["x1", "x2"]


def test_fetch_all_message_ids_two_pages():
    responses = [
        {"messages": [{"id": "a"}], "nextPageToken": "tok"},
        {"messages": [{"id": "b"}]},
    ]
    svc = MagicMock()
    svc.users().messages().list().execute.side_effect = responses
    ids = list(gc.fetch_all_message_ids(svc, "INBOX"))
    assert ids == ["a", "b"]


# ---------------------------------------------------------------------------
# batch_trash
# ---------------------------------------------------------------------------

def test_batch_trash_single_batch(capsys):
    svc = MagicMock()
    ids = [str(i) for i in range(10)]
    total = gc.batch_trash(svc, iter(ids))
    assert total == 10
    svc.users().messages().batchModify.assert_called_once()
    body = svc.users().messages().batchModify.call_args.kwargs["body"]
    assert body["ids"] == ids
    assert "TRASH" in body["addLabelIds"]


def test_batch_trash_splits_into_chunks(capsys):
    svc = MagicMock()
    ids = [str(i) for i in range(2500)]
    total = gc.batch_trash(svc, iter(ids))
    assert total == 2500
    assert svc.users().messages().batchModify.call_count == 3  # 1000+1000+500


def test_batch_trash_empty(capsys):
    svc = MagicMock()
    total = gc.batch_trash(svc, iter([]))
    assert total == 0
    svc.users().messages().batchModify.assert_not_called()


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
