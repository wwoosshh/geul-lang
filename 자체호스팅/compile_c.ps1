[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$hangeul = "" + [char]0xD55C + [char]0xAE00
$selfhost = "" + [char]0xC790 + [char]0xCCB4 + [char]0xD638 + [char]0xC2A4 + [char]0xD305
$ju = "" + [char]0xC8FC
$basePath = "C:\workspace\$hangeul"

$cFile = "$basePath\$selfhost\$ju.c"
$exeFile = "$basePath\$selfhost\${ju}_stage1.exe"

Write-Host "Compiling: $cFile"
Write-Host "Output: $exeFile"

$cl = "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC\14.44.35207\bin\Hostx64\x64\cl.exe"

& $cl /utf-8 /nologo /std:c11 `
    /I"C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC\14.44.35207\include" `
    /I"C:\Program Files (x86)\Windows Kits\10\Include\10.0.26100.0\ucrt" `
    /I"C:\Program Files (x86)\Windows Kits\10\Include\10.0.26100.0\um" `
    /I"C:\Program Files (x86)\Windows Kits\10\Include\10.0.26100.0\shared" `
    /Fe:$exeFile $cFile `
    /link `
    /LIBPATH:"C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC\14.44.35207\lib\x64" `
    /LIBPATH:"C:\Program Files (x86)\Windows Kits\10\Lib\10.0.26100.0\ucrt\x64" `
    /LIBPATH:"C:\Program Files (x86)\Windows Kits\10\Lib\10.0.26100.0\um\x64" 2>&1 | ForEach-Object { Write-Host $_ }

Write-Host ""
Write-Host "Exit: $LASTEXITCODE"
if (Test-Path $exeFile) {
    Write-Host "Size: $((Get-Item $exeFile).Length) bytes"
}
