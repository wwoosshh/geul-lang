[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$hangeul = "" + [char]0xD55C + [char]0xAE00
$selfhost = "" + [char]0xC790 + [char]0xCCB4 + [char]0xD638 + [char]0xC2A4 + [char]0xD305
$ju = "" + [char]0xC8FC
$geul = "" + [char]0xAE00
$basePath = "C:\workspace\$hangeul"
$compiler = "$basePath\$selfhost\$ju.exe"
$source = "$basePath\$selfhost\$ju.$geul"

Write-Host "=== Self-compile with stderr debug ==="
$proc = Start-Process -FilePath $compiler -ArgumentList "--emit-c",$source -NoNewWindow -PassThru -Wait -RedirectStandardError "$basePath\$selfhost\debug_stderr.txt"
Write-Host "Exit: $($proc.ExitCode)"
Write-Host ""
Write-Host "=== stderr output ==="
if (Test-Path "$basePath\$selfhost\debug_stderr.txt") {
    Get-Content "$basePath\$selfhost\debug_stderr.txt" -Encoding UTF8
}
