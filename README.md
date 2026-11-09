# Duplicate Detector Bot

Telegram channel mein duplicate files aur messages pakadne wala bot.

## Kaam
- Channel mein admin banao ("Delete Messages" permission ke saath).
- Har nayi post (file ya text) ko watch karta hai — naam + size ya text note karta hai.
- Ek hi naam + ek hi size ki file dobara aaye (ya ek hi text dobara aaye) to owner ko DM mein alert bhejta hai.
- Alert mein options: **Delete All** / **Keep First, Delete Rest** / **Delete Selected** / **Keep**.

## Setup
1. BotFather se bot banao, `BOT_TOKEN` lo.
2. Railway mein service variables set karo:
   - `BOT_TOKEN` — BotFather wala token
   - `API_ID`, `API_HASH` — my.telegram.org wale
   - `OWNER_ID` — owner ka Telegram user id (default 7966027018)
3. Start command: `python bot.py`

## Commands (DM)
- `/start` — shuruaat + setup guide
- `/help` — madad
- `/stats` — tracked files, duplicates, channels
- `/duplicates` — haal ke duplicates

## Note
Bot sirf add hone ke **baad** ki posts dekh sakta hai — purana channel history Bot API se read nahi hota.
