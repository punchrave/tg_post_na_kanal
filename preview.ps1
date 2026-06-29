$ErrorActionPreference = "Stop"

$messagesFile = ".\posts.txt"
if (-not (Test-Path $messagesFile)) {
    $messagesFile = ".\message.txt"
    python .\telegram_autoposter.py --message-file $messagesFile --dry-run
    exit $LASTEXITCODE
}

python .\telegram_autoposter.py --messages-file $messagesFile --dry-run
exit $LASTEXITCODE
