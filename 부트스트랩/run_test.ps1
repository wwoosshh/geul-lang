[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$hangeul = "" + [char]0xD55C + [char]0xAE00
$yeje = "" + [char]0xC608 + [char]0xC81C
$lexer = "" + [char]0xAC04 + [char]0xB2E8 + [char]0xB809 + [char]0xC11C
$basePath = "C:\workspace\$hangeul"
$exe = "$basePath\$yeje\$lexer.exe"

Write-Host "Running: $exe"
Write-Host "---"
& $exe 2>&1 | ForEach-Object { Write-Host $_ }
Write-Host "---"
Write-Host "Exit code: $LASTEXITCODE"
