[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$boot = "" + [char]0xBD80 + [char]0xD2B8 + [char]0xC2A4 + [char]0xD2B8 + [char]0xB7A9
$hangeul = "" + [char]0xD55C + [char]0xAE00
$bootPath = "C:\workspace\$hangeul\$boot"
Set-Location $bootPath

$env:PATH = "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC\14.44.35207\bin\Hostx64\x64;" + $env:PATH
$env:INCLUDE = "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC\14.44.35207\include;C:\Program Files (x86)\Windows Kits\10\Include\10.0.26100.0\ucrt;C:\Program Files (x86)\Windows Kits\10\Include\10.0.26100.0\um;C:\Program Files (x86)\Windows Kits\10\Include\10.0.26100.0\shared"
$env:LIB = "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC\14.44.35207\lib\x64;C:\Program Files (x86)\Windows Kits\10\Lib\10.0.26100.0\ucrt\x64;C:\Program Files (x86)\Windows Kits\10\Lib\10.0.26100.0\um\x64"

if (-not (Test-Path build)) { New-Item -ItemType Directory build | Out-Null }

$geul = "" + [char]0xAE00
$srcs = (Get-ChildItem "src\*.c").FullName
$outExe = "build\${geul}cc.exe"
Write-Host "Compiling $($srcs.Count) files..."
& cl /utf-8 /nologo /std:c11 /W3 /Iinclude $srcs "/Fe:$outExe" /link 2>&1 | ForEach-Object { Write-Host $_ }
if ($LASTEXITCODE -eq 0) {
    Write-Host "BUILD OK: $outExe"
    Remove-Item *.obj -ErrorAction SilentlyContinue
} else {
    Write-Host "BUILD FAILED"
    exit 1
}
