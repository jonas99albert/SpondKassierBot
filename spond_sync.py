"""Spond-Synchronisation: Events abrufen und Nicht-Antworter bestrafen."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from spond import spond
import database as db

logger = logging.getLogger(__name__)


async def sync_spond(email: str, password: str, group_id: str, penalty_amount: float, from_date: datetime = None) -> dict:
    """
    Synchronisiert mit Spond und bestraft Nicht-Antworter.

    Args:
        from_date: Ab wann Events geprüft werden (default: letzte 14 Tage)

    Returns:
        dict mit keys: events_checked, new_penalties, players_synced, skipped_expired, details
    """
    s = spond.Spond(username=email, password=password)
    result = {
        "events_checked": 0,
        "new_penalties": 0,
        "players_synced": 0,
        "skipped_expired": 0,
        "details": [],
    }

    try:
        # Zeitraum bestimmen
        now = datetime.now(timezone.utc)
        if from_date:
            min_date = from_date.replace(tzinfo=timezone.utc)
        else:
            min_date = now - timedelta(days=14)

        events = await s.get_events(
            group_id=group_id,
            min_start=min_date,
            max_end=now,
            include_scheduled=True,
            max_events=500,
        )

        # Gruppenmitglieder für Namenszuordnung
        group = await s.get_group(group_id)
        members = {m["id"]: m for m in group.get("members", [])}

        # ALLE Mitglieder in DB anlegen/aktualisieren
        for member_id, member in members.items():
            first_name = member.get("firstName", "")
            last_name = member.get("lastName", "")
            full_name = f"{first_name} {last_name}".strip()
            if full_name:
                db.get_or_create_player(full_name, spond_id=member_id)
                result["players_synced"] += 1

        result["events_checked"] = len(events)

        for event in events:
            event_id = event["id"]
            event_name = event.get("heading", "Unbekannt")
            start_time = event.get("startTimestamp", "")

            # Abgesagte Events ignorieren
            if event.get("cancelled", False):
                logger.info(f"Übersprungen (abgesagt): {event_name}")
                continue

            # Nur Events bestrafen, deren Deadline ABGELAUFEN ist
            if not event.get("expired", False):
                logger.info(f"Übersprungen (Deadline noch offen): {event_name}")
                result["skipped_expired"] += 1
                continue

            # unansweredIds direkt von Spond nutzen
            responses = event.get("responses", {})
            unanswered_ids = responses.get("unansweredIds", [])

            if not unanswered_ids:
                continue

            for member_id in unanswered_ids:
                # member_id kann String oder Dict sein
                if isinstance(member_id, dict):
                    member_id = member_id.get("id", "")
                
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