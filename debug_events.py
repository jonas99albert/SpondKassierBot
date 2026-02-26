#!/usr/bin/env python3
"""Debug: Zeigt die Struktur eines Spond-Events an."""

import asyncio
import json
import os
from dotenv import load_dotenv
from spond import spond
from datetime import datetime, timedelta, timezone

load_dotenv()

async def main():
    s = spond.Spond(
        username=os.getenv("SPOND_EMAIL"),
        password=os.getenv("SPOND_PASSWORD"),
    )
    group_id = os.getenv("SPOND_GROUP_ID")

    now = datetime.now(timezone.utc)
    events = await s.get_events(
        group_id=group_id,
        min_start=now - timedelta(days=30),
        max_end=now,
        include_scheduled=True,
        max_events=10,
    )

    print(f"\n{'='*60}")
    print(f"Gefundene Events: {len(events)}")
    print(f"{'='*60}\n")

    for e in events:
        print(f"📅 {e.get('heading', '?')} ({e.get('startTimestamp', '?')[:10]})")
        print(f"   expired:   {e.get('expired', '❌ FELD FEHLT')}")
        print(f"   cancelled: {e.get('cancelled', '❌ FELD FEHLT')}")
        print(f"   type:      {e.get('type', '?')}")

        # Alle Keys auf oberster Ebene zeigen
        print(f"   Alle Keys: {list(e.keys())}")

        # Felder die auf "cancel/delete/removed" hindeuten
        for key in e.keys():
            val = e[key]
            if isinstance(val, bool) or (isinstance(val, str) and val.lower() in ("cancelled", "deleted", "removed")):
                print(f"   >>> {key}: {val}")

        print()

    # Erstes Event komplett als JSON ausgeben
    if events:
        print(f"\n{'='*60}")
        print("Erstes Event komplett (JSON):")
        print(f"{'='*60}")
        print(json.dumps(events[0], indent=2, default=str))

    await s.clientsession.close()

asyncio.run(main())
