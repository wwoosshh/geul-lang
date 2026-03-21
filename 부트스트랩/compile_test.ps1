[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$hangeul = "" + [char]0xD55C + [char]0xAE00
$boot = "" + [char]0xBD80 + [char]0xD2B8 + [char]0xC2A4 + [char]0xD2B8 + [char]0xB7A9
$geul = "" + [char]0xAE00
$yeje = "" + [char]0xC608 + [char]0xC81C
$basePath = "C:\workspace\$hangeul"
$compiler = "$basePath\$boot\build\${geul}cc.exe"

# Get filename from file listing - find .글 files and use the most recently modified
$targetName = $args[0]
if (-not $targetName) {
    $targetName = "묶음배열테스트"
}

$source = "$basePath\$yeje\$targetName.$geul"
$exe = "$basePath\$yeje\$targetName.exe"

Write-Host "Compiling: $source"
Write-Host "Exists: $(Test-Path $source)"
& $compiler $source 2>&1 | ForEach-Object { Write-Host $_ }

if ($LASTEXITCODE -eq 0) {
    Write-Host "`nRunning: $exe"
    Write-Host "---"
    & $exe 2>&1 | ForEach-Object { Write-Host $_ }
    Write-Host "---"
    Write-Host "Exit code: $LASTEXITCODE"
} else {
    Write-Host "Compilation failed!"
    exit 1
}
