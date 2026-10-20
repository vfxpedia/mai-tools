# Sends the contents of tg-outbox.txt (UTF-8) to the MAI OS Telegram bot.
# STRICTLY ASCII source; the message body lives in the outbox file so Korean
# text never passes through the PS 5.1 script parser.
#
# NOTE: use ReadAllText, NOT Get-Content -Raw. Get-Content returns a string
# decorated with PS NoteProperties (PSPath, PSDrive, ...) and ConvertTo-Json
# serialises all of them, which sent a wall of JSON to the chat once already.
$ErrorActionPreference = 'Continue'
$logdir = 'C:\ssd-cleanup-logs'
$envf   = Join-Path $env:USERPROFILE '.claude\channels\telegram\.env'
$outbox = Join-Path $logdir 'tg-outbox.txt'
$errf   = Join-Path $logdir 'tg-error.log'

if (-not (Test-Path $outbox)) { Write-Output 'no outbox'; exit 1 }

$lines = Get-Content $envf
$tok = ($lines | Where-Object { $_ -like 'TELEGRAM_BOT_TOKEN=*' }) -replace '^TELEGRAM_BOT_TOKEN=',''
$cid = ($lines | Where-Object { $_ -like 'TELEGRAM_CHAT_ID=*' })   -replace '^TELEGRAM_CHAT_ID=',''

$text = [System.IO.File]::ReadAllText($outbox, [System.Text.Encoding]::UTF8)
if ([string]::IsNullOrWhiteSpace($text)) { Write-Output 'outbox empty'; exit 1 }

$payload = [ordered]@{
  chat_id                  = $cid
  text                     = $text
  parse_mode               = 'HTML'
  disable_web_page_preview = $true
}
$body  = ($payload | ConvertTo-Json -Compress)
$bytes = [System.Text.Encoding]::UTF8.GetBytes($body)

try {
  $r = Invoke-RestMethod -Uri "https://api.telegram.org/bot$tok/sendMessage" -Method Post `
       -ContentType 'application/json; charset=utf-8' -Body $bytes -TimeoutSec 30
  Write-Output "sent ok=$($r.ok)"
  "$(Get-Date -Format 'HH:mm:ss') outbox sent" | Out-File $errf -Encoding utf8 -Append
} catch {
  Write-Output "FAIL: $($_.Exception.Message)"
  "$(Get-Date -Format 'HH:mm:ss') outbox FAIL: $($_.Exception.Message)" | Out-File $errf -Encoding utf8 -Append
}
