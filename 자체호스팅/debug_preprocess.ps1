[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$hangeul = "" + [char]0xD55C + [char]0xAE00
$selfhost = "" + [char]0xC790 + [char]0xCCB4 + [char]0xD638 + [char]0xC2A4 + [char]0xD305
$ju = "" + [char]0xC8FC
$basePath = "C:\workspace\$hangeul"
$compiler = "$basePath\$selfhost\$ju.exe"

$testFile = $args[0]
if (-not $testFile) {
    $testFile = "test_incl_main"
}
$geul = "" + [char]0xAE00
$source = "$basePath\$selfhost\$testFile.$geul"

Write-Host "=== Debug preprocessing ==="
& $compiler "--emit-c" $source 2>&1 | ForEach-Object { Write-Host $_ }

$cFile = "$basePath\$selfhost\$testFile.c"
if (Test-Path $cFile) {
    Write-Host ""
    Write-Host "=== Generated C code ==="
    Get-Content $cFile -Encoding UTF8
}
