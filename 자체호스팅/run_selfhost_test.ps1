[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$hangeul = "" + [char]0xD55C + [char]0xAE00
$selfhost = "" + [char]0xC790 + [char]0xCCB4 + [char]0xD638 + [char]0xC2A4 + [char]0xD305
$ju = "" + [char]0xC8FC
$basePath = "C:\workspace\$hangeul"
$compiler = "$basePath\$selfhost\$ju.exe"

$testFile = $args[0]
if (-not $testFile) {
    $testFile = "test_self"
}
$geul = "" + [char]0xAE00
$source = "$basePath\$selfhost\$testFile.$geul"

Write-Host "=== Self-hosted compiler test ==="
Write-Host "Compiler: $compiler"
Write-Host "Source: $source"
Write-Host ""

& $compiler $source 2>&1 | ForEach-Object { Write-Host $_ }

if ($LASTEXITCODE -eq 0) {
    $exe = "$basePath\$selfhost\$testFile.exe"
    if (Test-Path $exe) {
        Write-Host ""
        Write-Host "=== Running output ==="
        & $exe 2>&1 | ForEach-Object { Write-Host $_ }
        Write-Host "=== Exit: $LASTEXITCODE ==="
    }
} else {
    Write-Host "COMPILE FAILED (exit code: $LASTEXITCODE)"
}
