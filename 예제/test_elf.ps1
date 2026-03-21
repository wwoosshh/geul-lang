# ELF 생성 테스트 스크립트
# 1. 네이티브컴파일러로 ELF 바이너리 생성
# 2. hex dump로 ELF 구조 검증
# 3. WSL 사용 가능 시 실행 테스트
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = 'Continue'

$compiler = 'C:\workspace\한글\자체호스팅\네이티브컴파일러.exe'
$source = 'C:\workspace\한글\예제\ELF테스트.글'
$output = 'C:\temp\hello_elf'

Write-Host "=== ELF 생성 테스트 ==="
Write-Host "컴파일러: $compiler"
Write-Host "소스: $source"
Write-Host "출력: $output"
Write-Host ""

# 1. ELF 바이너리 생성
Write-Host "--- 1. ELF 바이너리 생성 ---"
& $compiler --no-std --elf $source -출력 $output 2>&1 | ForEach-Object { Write-Host $_ }

if (-not (Test-Path $output)) {
    Write-Host "오류: ELF 파일이 생성되지 않았습니다."
    exit 1
}

$fileSize = (Get-Item $output).Length
Write-Host "파일 크기: $fileSize 바이트"
Write-Host ""

# 2. ELF 매직 바이트 확인
Write-Host "--- 2. ELF 헤더 검증 ---"
$bytes = [System.IO.File]::ReadAllBytes($output)

# 매직 바이트: 7F 45 4C 46
$magic = '{0:X2} {1:X2} {2:X2} {3:X2}' -f $bytes[0], $bytes[1], $bytes[2], $bytes[3]
Write-Host "매직 바이트: $magic (기대값: 7F 45 4C 46)"
if ($magic -eq '7F 45 4C 46') {
    Write-Host "[OK] ELF 매직 바이트 일치"
} else {
    Write-Host "[FAIL] ELF 매직 바이트 불일치"
}

# 클래스: 64비트
Write-Host "EI_CLASS: $($bytes[4]) (기대값: 2 = 64비트)"
# 엔디안: 리틀엔디안
Write-Host "EI_DATA: $($bytes[5]) (기대값: 1 = 리틀엔디안)"
# 타입: ET_EXEC
$etype = [BitConverter]::ToUInt16($bytes, 0x10)
Write-Host "e_type: $etype (기대값: 2 = ET_EXEC)"
# 머신: x86-64
$emachine = [BitConverter]::ToUInt16($bytes, 0x12)
Write-Host "e_machine: 0x$($emachine.ToString('X')) (기대값: 0x3E = x86-64)"
# 진입점
$entry = [BitConverter]::ToUInt64($bytes, 0x18)
Write-Host "e_entry: 0x$($entry.ToString('X')) (기대값: 0x401000)"
# 프로그램 헤더 수
$phnum = [BitConverter]::ToUInt16($bytes, 0x38)
Write-Host "e_phnum: $phnum (기대값: 2)"
Write-Host ""

# 3. .text 섹션 기계어 확인 (오프셋 0x1000)
Write-Host "--- 3. .text 섹션 (오프셋 0x1000) ---"
if ($bytes.Length -gt 0x1000) {
    $textStart = 0x1000
    $textLen = [Math]::Min(42, $bytes.Length - $textStart)
    $hexDump = ($bytes[$textStart..($textStart + $textLen - 1)] | ForEach-Object { '{0:X2}' -f $_ }) -join ' '
    Write-Host "기계어: $hexDump"
}
Write-Host ""

# 4. .rodata 섹션 확인 (오프셋 0x2000)
Write-Host "--- 4. .rodata 섹션 (오프셋 0x2000) ---"
if ($bytes.Length -gt 0x2000) {
    $dataStart = 0x2000
    $dataLen = [Math]::Min(12, $bytes.Length - $dataStart)
    $dataBytes = $bytes[$dataStart..($dataStart + $dataLen - 1)]
    $hexDump = ($dataBytes | ForEach-Object { '{0:X2}' -f $_ }) -join ' '
    $text = [System.Text.Encoding]::UTF8.GetString($dataBytes)
    Write-Host "데이터 (hex): $hexDump"
    Write-Host "데이터 (문자열): $text"
}
Write-Host ""

# 5. WSL에서 실행 테스트
Write-Host "--- 5. WSL 실행 테스트 ---"
$wslPath = '/mnt/c/temp/hello_elf'
try {
    $wslExists = Get-Command wsl -ErrorAction SilentlyContinue
    if ($wslExists) {
        Write-Host "WSL 발견, 실행 시도..."
        wsl chmod +x $wslPath 2>&1
        $result = wsl $wslPath 2>&1
        Write-Host "출력: $result"
        Write-Host "종료코드: $LASTEXITCODE"
    } else {
        Write-Host "WSL 미설치 - 실행 테스트 건너뜀"
        Write-Host "수동 테스트: WSL 또는 Linux에서 'chmod +x $output && ./hello_elf' 실행"
    }
} catch {
    Write-Host "WSL 실행 실패: $_"
    Write-Host "수동 테스트: WSL 또는 Linux에서 실행하세요"
}

Write-Host ""
Write-Host "=== 테스트 완료 ==="
