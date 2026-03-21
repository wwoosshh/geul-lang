[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$hangeul = "" + [char]0xD55C + [char]0xAE00
$selfhost = "" + [char]0xC790 + [char]0xCCB4 + [char]0xD638 + [char]0xC2A4 + [char]0xD305
$ju = "" + [char]0xC8FC
$basePath = "C:\workspace\$hangeul"

# Stage 0: Bootstrap compiler builds self-hosting compiler (already done as 주.exe)
$stage0 = "$basePath\$selfhost\$ju.exe"

# Stage 1: Self-hosting compiler compiles itself
$source = "$basePath\$selfhost\$ju.$([char]0xAE00)"
$stage1 = "$basePath\$selfhost\${ju}_stage1.exe"

Write-Host "=== Stage 1: Self-hosting compiler compiles itself ==="
Write-Host "Compiler: $stage0"
Write-Host "Source: $source"
Write-Host ""

# First emit C code to check for errors
& $stage0 "--emit-c" $source 2>&1 | ForEach-Object { Write-Host $_ }

$cFile = "$basePath\$selfhost\$ju.c"
if (Test-Path $cFile) {
    $cSize = (Get-Item $cFile).Length
    Write-Host "Generated C file: $cFile ($cSize bytes)"
} else {
    Write-Host "ERROR: No C file generated"
    exit 1
}
