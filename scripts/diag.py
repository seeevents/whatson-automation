#!/usr/bin/env python3
"""Diagnostic des secrets/connexions. Ecrit les resultats en annotations GitHub (::notice::/::error::)."""
import os
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import settings  # noqa: E402


def out(level, msg):
    print(f"::{level}::{msg}")


def check(name, fn):
    try:
        out("notice", f"{name}: {fn()}")
    except Exception as exc:  # noqa: BLE001
        out("error", f"{name}: {type(exc).__name__} {str(exc)[:300]}")


def airtable_read():
    r = requests.get(
        f"https://api.airtable.com/v0/{settings.AIRTABLE_BASE_ID}/{settings.AIRTABLE_TABLE_DEDUP}",
        headers={"Authorization": f"Bearer {os.environ.get('AIRTABLE_API_KEY','')}"},
        params={"maxRecords": 1}, timeout=30)
    return f"{r.status_code} {r.text[:200]}"


def airtable_events_count():
    r = requests.get(
        f"https://api.airtable.com/v0/{settings.AIRTABLE_BASE_ID}/{settings.AIRTABLE_TABLE_EVENTS}",
        headers={"Authorization": f"Bearer {os.environ.get('AIRTABLE_API_KEY','')}"},
        params={"pageSize": 100}, timeout=30)
    return f"{r.status_code} records={len(r.json().get('records', [])) if r.ok else r.text[:200]}"


def apify():
    r = requests.get("https://api.apify.com/v2/users/me/limits",
                     params={"token": os.environ.get("APIFY_API_TOKEN", "")}, timeout=30)
    if not r.ok:
        return f"{r.status_code} {r.text[:200]}"
    d = r.json().get("data", {})
    return f"limits={str(d.get('limits'))[:200]} current={str(d.get('current'))[:300]}"


def anthropic():
    r = requests.post("https://api.anthropic.com/v1/messages",
                      headers={"x-api-key": os.environ.get("ANTHROPIC_API_KEY", ""),
                               "anthropic-version": "2023-06-01", "content-type": "application/json"},
                      json={"model": "claude-haiku-4-5-20251001", "max_tokens": 5,
                            "messages": [{"role": "user", "content": "ok"}]}, timeout=30)
    return f"{r.status_code} {r.text[:200]}"


def graph():
    from src import accounts
    accs = accounts.get_todays_accounts(all_weekdays=True)
    return f"{len(accs)} comptes InstaCheck"


check("airtable_items_vus", airtable_read)
check("airtable_events_collectes", airtable_events_count)
check("apify", apify)
check("anthropic", anthropic)
check("msgraph_instacheck", graph)


def date_empty():
    h = {"Authorization": f"Bearer {os.environ.get('AIRTABLE_API_KEY','')}", "Content-Type": "application/json"}
    url = f"https://api.airtable.com/v0/{settings.AIRTABLE_BASE_ID}/{settings.AIRTABLE_TABLE_EVENTS}"
    res = []
    for label, val in (("vide", ""), ("valide", "2026-10-20")):
        r = requests.post(url, headers=h, json={"fields": {settings.FLD_TITRE: "DIAG - a supprimer", settings.FLD_DATE: val}}, timeout=30)
        res.append(f"{label}: {r.status_code} {r.text[:120] if not r.ok else 'ok'}")
        if r.ok:
            requests.delete(f"{url}/{r.json()['id']}", headers=h, timeout=30)
    return " | ".join(res)


check("date_vide", date_empty)
