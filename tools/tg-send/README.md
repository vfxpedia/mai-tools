# tg-send

The Windows sender that mai-watch, mai-resume and the session reports use to reach the owner's Telegram. It reads the text from standard input, sends it as plain text (no HTML parse mode, so `<` in a message cannot break it) and prints `sent ok=True` only when Telegram accepted it.

The bot token and chat id are not in this file. The script reads them from `%USERPROFILE%\.claude\channels\telegram\.env` (`TELEGRAM_BOT_TOKEN=` and `TELEGRAM_CHAT_ID=` lines), which stays on the machine and is never committed.

On AI-WS01 it lives at `C:\ssd-cleanup-logs\tg-send.ps1`; this copy is here so the setup can be rebuilt on another machine (10/20). The Linux sender is described in the mai-os Linux runbook, section 5.

Check after any change: send one known sentence and look at how it arrives on the phone, not only at `ok=True`.
