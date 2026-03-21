[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$hangeul = "" + [char]0xD55C + [char]0xAE00
$selfhost = "" + [char]0xC790 + [char]0xCCB4 + [char]0xD638 + [char]0xC2A4 + [char]0xD305
$ju = "" + [char]0xC8FC
$geul = "" + [char]0xAE00
$basePath = "C:\workspace\$hangeul"
$compiler = "$basePath\$selfhost\$ju.exe"

Write-Host "=== Test 1: No arguments ==="
& $compiler 2>&1
Write-Host "Exit: $LASTEXITCODE"
Write-Host ""

Write-Host "=== Test 2: --emit-c with source ==="
$source = "$basePath\$selfhost\$ju.$geul"
& $compiler "--emit-c" $source 2>&1 | Select-Object -First 20
Write-Host "Exit: $LASTEXITCODE"
