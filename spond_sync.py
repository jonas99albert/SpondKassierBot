"""Spond-Synchronisation: Events abrufen und Nicht-Antworter bestrafen."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from spond import spond
import database as db

logger = logging.getLogger(__name__)


def _extract_ids(responses: dict, key: str) -> set:
    """Extrahiert Member-IDs sicher aus einer Response-Liste.
    
    Die Spond API kann verschiedene Formate liefern:
    - Liste von Strings: ["id1", "id2"]
    - Liste von Dicts: [{"id": "id1"}, {"id": "id2"}]
    """
    items = responses.get(key, [])
    if not items:
        return set()
    
    result = set()
    for item in items:
        if isinstance(item, str):
            result.add(item)
        elif isinstance(item, dict):
            if "id" in item:
                result.add(item["id"])
    return result


async def sync_spond(email: str, password: str, group_id: str, penalty_amount: float) -> dict:
    """
    Synchronisiert mit Spond und bestraft Nicht-Antworter.

    Returns:
        dict mit keys: events_checked, new_penalties, players_synced, details
    """
    s = spond.Spond(username=email, password=password)
    result = {
        "events_checked": 0,
        "new_penalties": 0,
        "players_synced": 0,
        "details": [],
    }

    try:
        # Vergangene Events der letzten 14 Tage abrufen
        now = datetime.now(timezone.utc)
        min_date = now - timedelta(days=14)

        events = await s.get_events(
            group_id=group_id,
            min_start=min_date,
            max_end=now,
            include_scheduled=True,
        )

        # Gruppenmitglieder für Namenszuordnung
        group = await s.get_group(group_id)
        members = {m["id"]: m for m in group.get("members", [])}

        result["events_checked"] = len(events)

        # Debug: Erstes Event loggen um Struktur zu sehen
        if events:
            first = events[0]
            logger.info(f"Debug Event-Keys: {list(first.keys())}")
            resp = first.get("responses", {})
            logger.info(f"Debug Responses-Keys: {list(resp.keys())}")
            for rkey in resp:
                val = resp[rkey]
                if isinstance(val, list) and val:
                    logger.info(f"Debug responses['{rkey}'][0] type={type(val[0]).__name__}, value={val[0]}")

        for event in events:
            event_id = event["id"]
            event_name = event.get("heading", "Unbekannt")
            start_time = event.get("startTimestamp", "")

            # Responses auswerten (robust: String oder Dict)
            responses = event.get("responses", {})
            accepted_ids = _extract_ids(responses, "acceptedIds")
            declined_ids = _extract_ids(responses, "declinedIds")
            waiting_ids = _extract_ids(responses, "waitinglistIds")
            unconfirmed_ids = _extract_ids(responses, "unconfirmedIds")

            responded_ids = accepted_ids | declined_ids | waiting_ids | unconfirmed_ids

            # Alle Gruppenmitglieder gelten als eingeladen
            invited_member_ids = set(members.keys())

            # Nicht-Antworter finden
            no_reply_ids = invited_member_ids - responded_ids

            for member_id in no_reply_ids:
                member = members.get(member_id)
                if not member:
                    continue

                first_name = member.get("firstName", "")
                last_name = member.get("lastName", "")
                full_name = f"{first_name} {last_name}".strip()

                if not full_name:
                    continue

                # Spieler in DB anlegen/finden
                player = db.get_or_create_player(full_name, spond_id=member_id)
                result["players_synced"] += 1

                # Prüfen ob Strafe schon existiert
                if not db.penalty_exists(player["id"], event_id):
                    db.add_penalty(
                        player_id=player["id"],
                        reason=f"Spond nicht beantwortet: {event_name}",
                        amount=penalty_amount,
                        event_id=event_id,
                    )
                    result["new_penalties"] += 1
                    result["details"].append(
                        f"  ⚠️ {full_name} → {event_name} ({start_time[:10]})"
                    )

    finally:
        await s.clientsession.close()

    return result


async def list_spond_groups(email: str, password: str) -> list[dict]:
    """Listet alle Spond-Gruppen auf (zum Finden der Group-ID)."""
    s = spond.Spond(username=email, password=password)
    try:
        groups = await s.get_groups()
        return [{"id": g["id"], "name": g.get("name", "?")} for g in groups]
    finally:
        await s.clientsession.close()


async def get_spond_members(email: str, password: str, group_id: str) -> list[dict]:
    """Gibt alle Mitglieder einer Spond-Gruppe zurück."""
    s = spond.Spond(username=email, password=password)
    try:
        group = await s.get_group(group_id)
        members = []
        for m in group.get("members", []):
            name = f"{m.get('firstName', '')} {m.get('lastName', '')}".strip()
            members.append({"id": m["id"], "name": name})
        return members
    finally:
        await s.clientsession.close()