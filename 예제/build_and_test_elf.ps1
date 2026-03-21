# ELF 지원 네이티브 컴파일러 빌드 및 테스트
# 1단계: 자체호스팅 컴파일러(주.exe)로 네이티브컴파일러 트랜스파일
# 2단계: MSVC로 C 코드 컴파일
# 3단계: --elf 플래그로 ELF 바이너리 생성
# 4단계: ELF 구조 검증 + WSL 실행 테스트
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = 'Continue'

# Unicode 경로 구성
$hangeul = "" + [char]0xD55C + [char]0xAE00
$jache = "" + [char]0xC790 + [char]0xCCB4 + [char]0xD638 + [char]0xC2A4 + [char]0xD305
$geul = "" + [char]0xAE00
$native = "" + [char]0xB124 + [char]0xC774 + [char]0xD2F0 + [char]0xBE0C + [char]0xCEF4 + [char]0xD30C + [char]0xC77C + [char]0xB7EC
$yeje = "" + [char]0xC608 + [char]0xC81C
$ju = "" + [char]0xC8FC

$base = "C:\workspace\$hangeul"
$selfCompiler = "$base\$jache\$ju.exe"
$nativeSource = "$base\$jache\$native.$geul"
$nativeExe = "$base\$jache\$native.exe"
$outC = "C:\temp\nc_elf_build.c"
$elfTest = "$base\$yeje\ELF" + [char]0xD14C + [char]0xC2A4 + [char]0xD2B8 + ".$geul"
$elfOutput = "C:\temp\hello_elf"

Write-Host "========================================="
Write-Host " ELF 지원 네이티브 컴파일러 빌드"
Write-Host "========================================="
Write-Host ""

# 1단계: 트랜스파일
Write-Host "--- 1단계: 트랜스파일 ($nativeSource) ---"
$cOutput = & $selfCompiler $nativeSource 2>$null
if ($cOutput) {
    $cOutput | Set-Content -Path $outC -Encoding utf8
    Write-Host "  C 출력: $((Get-Item $outC).Length) bytes"
} else {
    Write-Host "  트랜스파일 실패!"
    exit 1
}

# 2단계: MSVC 컴파일
Write-Host ""
Write-Host "--- 2단계: MSVC 컴파일 ---"
$env:PATH = "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC\14.44.35207\bin\Hostx64\x64;" + $env:PATH
$env:INCLUDE = "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC\14.44.35207\include;C:\Program Files (x86)\Windows Kits\10\Include\10.0.26100.0\ucrt;C:\Program Files (x86)\Windows Kits\10\Include\10.0.26100.0\um;C:\Program Files (x86)\Windows Kits\10\Include\10.0.26100.0\shared"
$env:LIB = "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC\14.44.35207\lib\x64;C:\Program Files (x86)\Windows Kits\10\Lib\10.0.26100.0\ucrt\x64;C:\Program Files (x86)\Windows Kits\10\Lib\10.0.26100.0\um\x64"

Push-Location C:\temp
& cl /utf-8 /nologo /std:c11 /O2 $outC "/Fe:$nativeExe" /link 2>&1 | Select-Object -Last 5 | ForEach-Object { Write-Host "  $_" }
Pop-Location

if ($LASTEXITCODE -ne 0) {
    Write-Host "  MSVC 컴파일 실패!"
    exit 1
}
Write-Host "  빌드 성공: $nativeExe"
Remove-Item C:\temp\nc_elf_build.obj -ErrorAction SilentlyContinue

# 3단계: ELF 바이너리 생성
Write-Host ""
Write-Host "--- 3단계: ELF 바이너리 생성 ---"
& $nativeExe --no-std --elf $elfTest -출력 $elfOutput 2>&1 | ForEach-Object { Write-Host "  $_" }

if (-not (Test-Path $elfOutput)) {
    Write-Host "  ELF 파일 미생성!"
    exit 1
}
$fileSize = (Get-Item $elfOutput).Length
Write-Host "  파일 크기: $fileSize bytes"

# 4단계: ELF 구조 검증
Write-Host ""
Write-Host "--- 4단계: ELF 구조 검증 ---"
$bytes = [System.IO.File]::ReadAllBytes($elfOutput)

$magic = '{0:X2} {1:X2} {2:X2} {3:X2}' -f $bytes[0], $bytes[1], $bytes[2], $bytes[3]
$class = $bytes[4]
$data = $bytes[5]
$etype = [BitConverter]::ToUInt16($bytes, 0x10)
$emachine = [BitConverter]::ToUInt16($bytes, 0x12)
$entry = [BitConverter]::ToUInt64($bytes, 0x18)
$phnum = [BitConverter]::ToUInt16($bytes, 0x38)

$allOK = $true
function Check($name, $actual, $expected) {
    if ($actual -eq $expected) {
        Write-Host "  [OK] ${name}: $actual"
    } else {
        Write-Host "  [FAIL] ${name}: $actual (기대: $expected)"
        $script:allOK = $false
    }
}

Check "매직" $magic "7F 45 4C 46"
Check "클래스(64비트)" $class 2
Check "엔디안(LE)" $data 1
Check "타입(ET_EXEC)" $etype 2
Check "머신(x86-64)" "0x$($emachine.ToString('X'))" "0x3E"
Check "진입점" "0x$($entry.ToString('X'))" "0x401000"
Check "프로그램헤더수" $phnum 2

# .rodata 확인
if ($bytes.Length -gt 0x200C) {
    $msg = [System.Text.Encoding]::UTF8.GetString($bytes, 0x2000, 12)
    $expected = "Hello, " + [char]0xAE00 + "!`n"
    if ($msg -eq $expected) {
        Write-Host "  [OK] .rodata: 'Hello, 글!\\n'"
    } else {
        $hex = ($bytes[0x2000..0x200B] | ForEach-Object { '{0:X2}' -f $_ }) -join ' '
        Write-Host "  [INFO] .rodata hex: $hex"
    }
}

Write-Host ""

# 5단계: WSL 실행 (선택)
Write-Host "--- 5단계: WSL 실행 테스트 ---"
try {
    $wsl = Get-Command wsl -ErrorAction SilentlyContinue
    if ($wsl) {
        wsl chmod +x /mnt/c/temp/hello_elf 2>$null
        $result = wsl /mnt/c/temp/hello_elf 2>&1
        Write-Host "  WSL 출력: $result"
        Write-Host "  종료코드: $LASTEXITCODE"
    } else {
        Write-Host "  WSL 미설치 - 건너뜀"
    }
} catch {
    Write-Host "  WSL 실행 실패: $_"
}

Write-Host ""
if ($allOK) {
    Write-Host "========================================="
    Write-Host " 모든 검증 통과!"
    Write-Host "========================================="
} else {
    Write-Host "========================================="
    Write-Host " 일부 검증 실패"
    Write-Host "========================================="
}
