# ⚽ Strafenkasse Bot

Telegram Bot zur Verwaltung der Mannschaftskasse mit Spond-Integration.

## Features

- **Spond-Sync**: Automatisch Nicht-Antworter bestrafen (2€ pro Event)
- **Strafenkatalog**: Konfigurierbare Strafen (Gelbe Karte, Rote Karte, etc.)
- **Interaktive Vergabe**: Spieler & Strafe per Inline-Buttons wählen
- **Übersicht**: Tabelle aller offenen Strafen
- **CSV-Export**: Für Excel/Buchhaltung
- **Bezahlt-Markierung**: Strafen als beglichen markieren

## Setup auf dem Raspberry Pi

### 1. Bot-Token holen

1. Öffne Telegram → Suche `@BotFather`
2. `/newbot` → Name und Username vergeben
3. Token kopieren

### 2. Projekt auf den Pi kopieren

```bash
# Auf dem Pi:
cd ~
# Ordner strafenkasse-bot hierher kopieren (z.B. per SCP)

cd strafenkasse-bot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Konfiguration

```bash
cp .env.example .env
nano .env
```

Ausfüllen:
- `TELEGRAM_BOT_TOKEN` → Token vom BotFather
- `SPOND_EMAIL` → Deine Spond E-Mail
- `SPOND_PASSWORD` → Dein Spond Passwort
- `ADMIN_CHAT_IDS` → Deine Telegram ID (bekommst du mit /start)

### 4. Spond Group-ID finden

```bash
source venv/bin/activate
python bot.py
```

Dann im Bot: `/spond_gruppen` → ID kopieren → in `.env` eintragen → Bot neustarten.

### 5. Autostart einrichten

```bash
sudo cp strafenkasse-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable strafenkasse-bot
sudo systemctl start strafenkasse-bot

# Status prüfen:
sudo systemctl status strafenkasse-bot

# Logs anschauen:
journalctl -u strafenkasse-bot -f
```

## Befehle

| Befehl | Beschreibung |
|--------|-------------|
| `/start` | Hilfe anzeigen |
| `/strafen` | Offene Strafen (Tabelle) |
| `/strafe` | Strafe vergeben (interaktiv) |
| `/strafe_direkt Max Müller \| Grund \| 5` | Strafe direkt vergeben |
| `/bezahlt Max Müller` | Alle Strafen als bezahlt markieren |
| `/detail Max Müller` | Einzelstrafen eines Spielers |
| `/katalog` | Strafenkatalog anzeigen |
| `/katalog_add Meckern \| 2` | Neue Strafe zum Katalog |
| `/katalog_del Meckern` | Strafe aus Katalog entfernen |
| `/spond_sync` | Mit Spond abgleichen |
| `/spond_gruppen` | Spond-Gruppen anzeigen |
| `/spieler` | Alle Spieler auflisten |
| `/export` | CSV-Export |

## Standard-Strafenkatalog

| Strafe | Betrag |
|--------|--------|
| Spond nicht beantwortet | 2,00 € |
| Gelbe Karte | 5,00 € |
| Gelb-Rot | 10,00 € |
| Rote Karte | 15,00 € |
| Zu spät zum Training | 3,00 € |
| Trikot vergessen | 5,00 € |

Alle Einträge können per `/katalog_add` und `/katalog_del` angepasst werden.
