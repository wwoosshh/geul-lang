[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$hangeul = "" + [char]0xD55C + [char]0xAE00
$boot = "" + [char]0xBD80 + [char]0xD2B8 + [char]0xC2A4 + [char]0xD2B8 + [char]0xB7A9
$geul = "" + [char]0xAE00
$selfhost = "" + [char]0xC790 + [char]0xCCB4 + [char]0xD638 + [char]0xC2A4 + [char]0xD305
$ju = "" + [char]0xC8FC
$basePath = "C:\workspace\$hangeul"
$compiler = "$basePath\$boot\build\${geul}cc.exe"
$source = "$basePath\$selfhost\$ju.$geul"

Write-Host "=== Building self-hosting compiler ==="
Write-Host "Compiler: $compiler"
Write-Host "Source: $source"
Write-Host ""

& $compiler $source 2>&1 | ForEach-Object { Write-Host $_ }

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "BUILD SUCCESS"
    $exePath = "$basePath\$selfhost\$ju.exe"
    Write-Host "Output: $exePath"
    if (Test-Path $exePath) {
        Write-Host "Size: $((Get-Item $exePath).Length) bytes"
    }
} else {
    Write-Host ""
    Write-Host "BUILD FAILED (exit code: $LASTEXITCODE)"
}
