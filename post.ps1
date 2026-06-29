$ErrorActionPreference = "Stop"

$messagesFile = ".\posts.txt"
$useBlocks = Test-Path $messagesFile

if ($useBlocks) {
    python .\telegram_autoposter.py --messages-file $messagesFile --dry-run
} else {
    $messagesFile = ".\message.txt"
    python .\telegram_autoposter.py --message-file $messagesFile --dry-run
}

if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

$answer = Read-Host "Send these posts? Type YES to continue"
if ($answer -ne "YES") {
    Write-Host "Cancelled. No messages were posted."
    exit 0
}

if ($useBlocks) {
    python .\telegram_autoposter.py --messages-file $messagesFile
} else {
    python .\telegram_autoposter.py --message-file $messagesFile
}

exit $LASTEXITCODE
