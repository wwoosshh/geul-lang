[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$hangeul = "" + [char]0xD55C + [char]0xAE00
$selfhost = "" + [char]0xC790 + [char]0xCCB4 + [char]0xD638 + [char]0xC2A4 + [char]0xD305
$ju = "" + [char]0xC8FC
$geul = "" + [char]0xAE00
$basePath = "C:\workspace\$hangeul"

$compiler = "$basePath\$selfhost\$ju.exe"
$source = "$basePath\$selfhost\$ju.$geul"

Write-Host "Compiler: $compiler"
Write-Host "Source: $source"
Write-Host "Source exists: $(Test-Path $source)"
Write-Host ""

$output = & $compiler "--emit-c" $source 2>&1
foreach ($line in $output) {
    Write-Host $line
}
Write-Host ""
Write-Host "Exit code: $LASTEXITCODE"
