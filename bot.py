#!/usr/bin/env python3
"""
Strafenkasse Bot – Telegram Bot für die Mannschaftskasse.

Befehle:
  /start           – Begrüßung & Hilfe
  /strafen         – Übersicht aller offenen Strafen
  /strafe          – Strafe an Spieler vergeben (interaktiv)
  /bezahlt         – Strafen als bezahlt markieren
  /katalog         – Strafenkatalog anzeigen
  /katalog_add     – Neue Strafe zum Katalog hinzufügen
  /katalog_del     – Strafe aus Katalog entfernen
  /spond_sync      – Mit Spond synchronisieren
  /spond_gruppen   – Verfügbare Spond-Gruppen anzeigen
  /spieler         – Alle Spieler auflisten
  /detail          – Detail-Strafen eines Spielers
  /export          – CSV-Export der Strafen
"""

import asyncio
import csv
import io
import logging
import os
from datetime import datetime, timedelta

from dotenv import load_dotenv
from tabulate import tabulate
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

import database as db
from spond_sync import sync_spond, list_spond_groups

# ── Konfiguration ────────────────────────────────────────────────────

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SPOND_EMAIL = os.getenv("SPOND_EMAIL")
SPOND_PASSWORD = os.getenv("SPOND_PASSWORD")
SPOND_GROUP_ID = os.getenv("SPOND_GROUP_ID", "")
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_CHAT_IDS", "").split(",") if x.strip()]
NO_REPLY_PENALTY = float(os.getenv("SPOND_NO_REPLY_PENALTY", "2.00"))

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Conversation States
SELECT_PLAYER, SELECT_REASON, CONFIRM_PENALTY = range(3)


# ── Hilfsfunktionen ─────────────────────────────────────────────────

def is_admin(update: Update) -> bool:
    """Prüft ob der User ein Admin ist."""
    if not ADMIN_IDS:
        return True  # Wenn keine Admins konfiguriert, darf jeder
    return update.effective_user.id in ADMIN_IDS


def format_euro(amount: float) -> str:
    return f"{amount:.2f} €"


# ── /start ───────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "⚽ *Strafenkasse Bot*\n\n"
        "Ich verwalte die Mannschaftskasse\\. Hier sind meine Befehle:\n\n"
        "💰 *Strafen*\n"
        "/strafen – Übersicht offene Strafen\n"
        "/strafe – Strafe vergeben\n"
        "/bezahlt `Name` – Als bezahlt markieren\n"
        "/detail `Name` – Einzelstrafen anzeigen\n\n"
        "📋 *Katalog*\n"
        "/katalog – Strafenkatalog anzeigen\n"
        "/katalog\\_add `Name` `Betrag` – Neue Strafe\n"
        "/katalog\\_del `Name` – Strafe entfernen\n\n"
        "🔄 *Spond*\n"
        "/spond\\_sync `01.01.2026` – Spond abgleichen ab Datum\n"
        "/spond\\_gruppen – Gruppen anzeigen\n\n"
        "📊 *Sonstiges*\n"
        "/spieler – Alle Spieler\n"
        "/export – CSV\\-Export\n\n"
        f"Deine Chat\\-ID: `{update.effective_user.id}`"
    )
    await update.message.reply_text(text, parse_mode="MarkdownV2")


# ── /strafen ─────────────────────────────────────────────────────────

async def cmd_strafen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Zeigt Übersicht aller offenen Strafen als Tabelle."""
    summary = db.get_penalty_summary(only_unpaid=True)

    if not summary:
        await update.message.reply_text("✅ Keine offenen Strafen! Die Kasse ist sauber.")
        return

    total = db.get_total_open()

    table_data = []
    for s in summary:
        table_data.append([s["name"], s["anzahl"], format_euro(s["summe"])])

    table = tabulate(
        table_data,
        headers=["Spieler", "Anz.", "Summe"],
        tablefmt="simple",
        colalign=("left", "center", "right"),
    )

    text = (
        f"💰 <b>Offene Strafen</b>\n\n"
        f"<pre>{table}</pre>\n\n"
        f"<b>Gesamt: {format_euro(total)}</b>"
    )
    await update.message.reply_text(text, parse_mode="HTML")


# ── /strafe (interaktiv mit Inline-Buttons) ──────────────────────────

async def cmd_strafe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Startet den interaktiven Strafen-Dialog."""
    if not is_admin(update):
        await update.message.reply_text("⛔ Nur Admins dürfen Strafen vergeben.")
        return ConversationHandler.END

    players = db.get_all_players()

    if not players:
        await update.message.reply_text(
            "❌ Noch keine Spieler vorhanden.\n"
            "Nutze /spond_sync um Spieler aus Spond zu importieren,\n"
            "oder vergib eine Strafe direkt:\n"
            "/strafe_direkt Vorname Nachname | Grund | Betrag"
        )
        return ConversationHandler.END

    # Spieler-Buttons erstellen (2 pro Zeile)
    buttons = []
    row = []
    for p in players:
        row.append(InlineKeyboardButton(p["name"], callback_data=f"sp_{p['id']}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    buttons.append([InlineKeyboardButton("❌ Abbrechen", callback_data="sp_cancel")])

    await update.message.reply_text(
        "👤 Wähle einen Spieler:",
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    return SELECT_PLAYER


async def select_player_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Spieler wurde gewählt, zeige Strafenkatalog."""
    query = update.callback_query
    await query.answer()

    if query.data == "sp_cancel":
        await query.edit_message_text("❌ Abgebrochen.")
        return ConversationHandler.END

    player_id = int(query.data.replace("sp_", ""))
    context.user_data["penalty_player_id"] = player_id

    player = db.find_player("")  # Fallback
    for p in db.get_all_players():
        if p["id"] == player_id:
            player = p
            break
    context.user_data["penalty_player_name"] = player["name"]

    # Katalog-Buttons
    catalog = db.get_catalog()
    buttons = []
    for item in catalog:
        label = f"{item['name']} ({format_euro(item['amount'])})"
        buttons.append([InlineKeyboardButton(label, callback_data=f"cat_{item['id']}")])

    buttons.append([InlineKeyboardButton("✏️ Eigener Grund", callback_data="cat_custom")])
    buttons.append([InlineKeyboardButton("❌ Abbrechen", callback_data="cat_cancel")])

    await query.edit_message_text(
        f"👤 Spieler: *{player['name']}*\n\n📋 Wähle die Strafe:",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown",
    )
    return SELECT_REASON


async def select_reason_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Strafengrund gewählt, Strafe eintragen."""
    query = update.callback_query
    await query.answer()

    if query.data == "cat_cancel":
        await query.edit_message_text("❌ Abgebrochen.")
        return ConversationHandler.END

    if query.data == "cat_custom":
        await query.edit_message_text(
            f"✏️ Spieler: *{context.user_data['penalty_player_name']}*\n\n"
            "Schreibe den Grund und Betrag so:\n"
            "`Grund | Betrag`\n\n"
            "Beispiel: `Bier vergessen | 5`",
            parse_mode="Markdown",
        )
        return CONFIRM_PENALTY

    # Aus Katalog
    catalog_id = int(query.data.replace("cat_", ""))
    catalog = db.get_catalog()
    item = next((c for c in catalog if c["id"] == catalog_id), None)

    if not item:
        await query.edit_message_text("❌ Strafe nicht gefunden.")
        return ConversationHandler.END

    penalty = db.add_penalty(
        player_id=context.user_data["penalty_player_id"],
        reason=item["name"],
        amount=item["amount"],
    )

    await query.edit_message_text(
        f"✅ Strafe eingetragen!\n\n"
        f"👤 {context.user_data['penalty_player_name']}\n"
        f"📝 {item['name']}\n"
        f"💰 {format_euro(item['amount'])}",
    )
    return ConversationHandler.END


async def custom_penalty_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Verarbeitet benutzerdefinierte Strafe: Grund | Betrag"""
    text = update.message.text.strip()

    if "|" not in text:
        await update.message.reply_text(
            "❌ Format: `Grund | Betrag`\nBeispiel: `Bier vergessen | 5`",
            parse_mode="Markdown",
        )
        return CONFIRM_PENALTY

    parts = text.split("|", 1)
    reason = parts[0].strip()
    try:
        amount = float(parts[1].strip().replace(",", ".").replace("€", ""))
    except ValueError:
        await update.message.reply_text("❌ Betrag konnte nicht gelesen werden.")
        return CONFIRM_PENALTY

    penalty = db.add_penalty(
        player_id=context.user_data["penalty_player_id"],
        reason=reason,
        amount=amount,
    )

    await update.message.reply_text(
        f"✅ Strafe eingetragen!\n\n"
        f"👤 {context.user_data['penalty_player_name']}\n"
        f"📝 {reason}\n"
        f"💰 {format_euro(amount)}",
    )
    return ConversationHandler.END


# ── /strafe_direkt (Schnellbefehl) ───────────────────────────────────

async def cmd_strafe_direkt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Direkte Strafe: /strafe_direkt Max Mustermann | Grund | Betrag"""
    if not is_admin(update):
        await update.message.reply_text("⛔ Nur Admins dürfen Strafen vergeben.")
        return

    text = " ".join(context.args) if context.args else ""
    parts = text.split("|")

    if len(parts) != 3:
        await update.message.reply_text(
            "❌ Format: `/strafe_direkt Name | Grund | Betrag`\n"
            "Beispiel: `/strafe_direkt Max Müller | Gelbe Karte | 5`",
            parse_mode="Markdown",
        )
        return

    name = parts[0].strip()
    reason = parts[1].strip()
    try:
        amount = float(parts[2].strip().replace(",", ".").replace("€", ""))
    except ValueError:
        await update.message.reply_text("❌ Betrag ungültig.")
        return

    # Prüfe ob Grund im Katalog ist → Betrag übernehmen
    catalog_entry = db.find_catalog_entry(reason)
    if catalog_entry:
        amount = catalog_entry["amount"]
        reason = catalog_entry["name"]

    player = db.get_or_create_player(name)
    db.add_penalty(player["id"], reason, amount)

    await update.message.reply_text(
        f"✅ Strafe eingetragen!\n\n"
        f"👤 {player['name']}\n"
        f"📝 {reason}\n"
        f"💰 {format_euro(amount)}",
    )


# ── /bezahlt ─────────────────────────────────────────────────────────

async def cmd_bezahlt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Markiert alle offenen Strafen eines Spielers als bezahlt."""
    if not is_admin(update):
        await update.message.reply_text("⛔ Nur Admins dürfen Zahlungen bestätigen.")
        return

    name = " ".join(context.args) if context.args else ""
    if not name:
        await update.message.reply_text("❌ Bitte Spielername angeben: `/bezahlt Max Müller`", parse_mode="Markdown")
        return

    player = db.find_player(name)
    if not player:
        await update.message.reply_text(f"❌ Spieler '{name}' nicht gefunden.")
        return

    count = db.mark_paid(player["id"])

    if count == 0:
        await update.message.reply_text(f"ℹ️ {player['name']} hat keine offenen Strafen.")
    else:
        await update.message.reply_text(
            f"✅ {count} Strafe(n) von *{player['name']}* als bezahlt markiert\\!",
            parse_mode="MarkdownV2",
        )


# ── /detail ──────────────────────────────────────────────────────────

async def cmd_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Zeigt Einzelstrafen eines Spielers."""
    name = " ".join(context.args) if context.args else ""
    if not name:
        await update.message.reply_text("❌ Bitte Spielername angeben: `/detail Max Müller`", parse_mode="Markdown")
        return

    player = db.find_player(name)
    if not player:
        await update.message.reply_text(f"❌ Spieler '{name}' nicht gefunden.")
        return

    penalties = db.get_penalties(player_id=player["id"])

    if not penalties:
        await update.message.reply_text(f"✅ {player['name']} hat keine Strafen.")
        return

    lines = [f"📋 <b>Strafen von {player['name']}</b>\n"]
    total_open = 0.0

    for p in penalties:
        status = "✅" if p["paid"] else "❌"
        date = p["created_at"][:10] if p["created_at"] else "?"
        lines.append(f"{status} {date} | {p['reason']} | {format_euro(p['amount'])}")
        if not p["paid"]:
            total_open += p["amount"]

    lines.append(f"\n<b>Offen: {format_euro(total_open)}</b>")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


# ── /katalog ─────────────────────────────────────────────────────────

async def cmd_katalog(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Zeigt den Strafenkatalog."""
    catalog = db.get_catalog()

    if not catalog:
        await update.message.reply_text("📋 Strafenkatalog ist leer.")
        return

    lines = ["📋 <b>Strafenkatalog</b>\n"]
    for item in catalog:
        lines.append(f"  • {item['name']}: <b>{format_euro(item['amount'])}</b>")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def cmd_katalog_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fügt Strafe zum Katalog hinzu: /katalog_add Name | Betrag"""
    if not is_admin(update):
        await update.message.reply_text("⛔ Nur für Admins.")
        return

    text = " ".join(context.args) if context.args else ""
    if "|" not in text:
        await update.message.reply_text(
            "❌ Format: `/katalog_add Name | Betrag`\n"
            "Beispiel: `/katalog_add Meckern | 2`",
            parse_mode="Markdown",
        )
        return

    parts = text.split("|", 1)
    name = parts[0].strip()
    try:
        amount = float(parts[1].strip().replace(",", ".").replace("€", ""))
    except ValueError:
        await update.message.reply_text("❌ Betrag ungültig.")
        return

    entry = db.add_catalog_entry(name, amount)
    await update.message.reply_text(f"✅ Katalog aktualisiert: {name} = {format_euro(amount)}")


async def cmd_katalog_del(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entfernt Strafe aus Katalog: /katalog_del Name"""
    if not is_admin(update):
        await update.message.reply_text("⛔ Nur für Admins.")
        return

    name = " ".join(context.args) if context.args else ""
    if not name:
        await update.message.reply_text("❌ Bitte Name angeben: `/katalog_del Meckern`", parse_mode="Markdown")
        return

    if db.remove_catalog_entry(name):
        await update.message.reply_text(f"✅ '{name}' aus Katalog entfernt.")
    else:
        await update.message.reply_text(f"❌ '{name}' nicht im Katalog gefunden.")


# ── /spieler ─────────────────────────────────────────────────────────

async def cmd_spieler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Listet alle bekannten Spieler auf."""
    players = db.get_all_players()

    if not players:
        await update.message.reply_text("📋 Noch keine Spieler vorhanden.\nNutze /spond_sync zum Import.")
        return

    lines = [f"👥 <b>{len(players)} Spieler</b>\n"]
    for p in players:
        spond_tag = " 🔗" if p.get("spond_id") else ""
        lines.append(f"  • {p['name']}{spond_tag}")

    lines.append("\n🔗 = mit Spond verknüpft")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


# ── /spond_sync ──────────────────────────────────────────────────────

async def cmd_spond_sync(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Synchronisiert mit Spond. Optional: /spond_sync 01.01.2026"""
    if not is_admin(update):
        await update.message.reply_text("⛔ Nur für Admins.")
        return

    if not SPOND_GROUP_ID:
        await update.message.reply_text(
            "❌ Keine SPOND_GROUP_ID konfiguriert.\n"
            "Nutze /spond_gruppen um deine Gruppen-ID zu finden."
        )
        return

    # Startdatum parsen (optional)
    date_arg = " ".join(context.args) if context.args else ""
    if date_arg:
        for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
            try:
                from_date = datetime.strptime(date_arg, fmt).replace(tzinfo=None)
                break
            except ValueError:
                continue
        else:
            await update.message.reply_text(
                "❌ Datumsformat nicht erkannt.\n"
                "Beispiele: `/spond_sync 01.01.2026` oder `/spond_sync 2026-01-01`",
                parse_mode="Markdown",
            )
            return
        date_label = date_arg
    else:
        from_date = datetime.now() - timedelta(days=14)
        date_label = f"letzten 14 Tage"

    msg = await update.message.reply_text(f"🔄 Synchronisiere mit Spond ({date_label})...")

    try:
        result = await sync_spond(
            email=SPOND_EMAIL,
            password=SPOND_PASSWORD,
            group_id=SPOND_GROUP_ID,
            penalty_amount=NO_REPLY_PENALTY,
            from_date=from_date,
        )

        text = (
            f"✅ <b>Spond-Sync abgeschlossen</b>\n\n"
            f"📆 Zeitraum: {date_label}\n"
            f"📅 Events geprüft: {result['events_checked']}\n"
            f"⏭️ Übersprungen (Deadline offen): {result['skipped_expired']}\n"
            f"⚠️ Neue Strafen: {result['new_penalties']}\n"
        )

        if result["details"]:
            text += "\n<b>Neue Einträge:</b>\n"
            text += "\n".join(result["details"][:20])  # Max 20 anzeigen

            if len(result["details"]) > 20:
                text += f"\n... und {len(result['details']) - 20} weitere"

        await msg.edit_text(text, parse_mode="HTML")

    except Exception as e:
        logger.error(f"Spond sync error: {e}", exc_info=True)
        await msg.edit_text(f"❌ Spond-Fehler: {str(e)[:200]}")


async def cmd_spond_gruppen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Zeigt alle Spond-Gruppen zum Finden der Group-ID."""
    if not is_admin(update):
        await update.message.reply_text("⛔ Nur für Admins.")
        return

    msg = await update.message.reply_text("🔄 Lade Spond-Gruppen...")

    try:
        groups = await list_spond_groups(SPOND_EMAIL, SPOND_PASSWORD)
        lines = ["📋 <b>Deine Spond-Gruppen</b>\n"]
        for g in groups:
            lines.append(f"  • {g['name']}\n    <code>{g['id']}</code>")
        lines.append("\nKopiere die ID und trage sie als SPOND_GROUP_ID in die .env ein.")
        await msg.edit_text("\n".join(lines), parse_mode="HTML")
    except Exception as e:
        logger.error(f"Spond groups error: {e}", exc_info=True)
        await msg.edit_text(f"❌ Fehler: {str(e)[:200]}")


# ── /export ──────────────────────────────────────────────────────────

async def cmd_export(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Exportiert alle Strafen als CSV."""
    penalties = db.get_penalties()

    if not penalties:
        await update.message.reply_text("📋 Keine Strafen vorhanden.")
        return

    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(["Spieler", "Grund", "Betrag", "Bezahlt", "Datum", "Bezahlt am"])

    for p in penalties:
        writer.writerow([
            p["player_name"],
            p["reason"],
            f"{p['amount']:.2f}",
            "Ja" if p["paid"] else "Nein",
            p["created_at"][:10] if p["created_at"] else "",
            p["paid_at"][:10] if p.get("paid_at") else "",
        ])

    output.seek(0)
    date_str = datetime.now().strftime("%Y-%m-%d")

    await update.message.reply_document(
        document=output.getvalue().encode("utf-8-sig"),
        filename=f"strafenkasse_{date_str}.csv",
        caption=f"📊 Export vom {date_str}",
    )


# ── Fallback für Conversation ────────────────────────────────────────

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Abgebrochen.")
    return ConversationHandler.END


# ── Main ─────────────────────────────────────────────────────────────

def main():
    if not BOT_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN nicht gesetzt! Bitte .env Datei prüfen.")
        return

    db.init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    # Conversation Handler für interaktive Strafe
    penalty_conv = ConversationHandler(
        entry_points=[CommandHandler("strafe", cmd_strafe)],
        states={
            SELECT_PLAYER: [CallbackQueryHandler(select_player_callback, pattern=r"^sp_")],
            SELECT_REASON: [CallbackQueryHandler(select_reason_callback, pattern=r"^cat_")],
            CONFIRM_PENALTY: [MessageHandler(filters.TEXT & ~filters.COMMAND, custom_penalty_input)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(penalty_conv)

    # Einfache Befehle
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("strafen", cmd_strafen))
    app.add_handler(CommandHandler("strafe_direkt", cmd_strafe_direkt))
    app.add_handler(CommandHandler("bezahlt", cmd_bezahlt))
    app.add_handler(CommandHandler("detail", cmd_detail))
    app.add_handler(CommandHandler("katalog", cmd_katalog))
    app.add_handler(CommandHandler("katalog_add", cmd_katalog_add))
    app.add_handler(CommandHandler("katalog_del", cmd_katalog_del))
    app.add_handler(CommandHandler("spieler", cmd_spieler))
    app.add_handler(CommandHandler("spond_sync", cmd_spond_sync))
    app.add_handler(CommandHandler("spond_gruppen", cmd_spond_gruppen))
    app.add_handler(CommandHandler("export", cmd_export))

    print("🤖 Strafenkasse Bot gestartet!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()