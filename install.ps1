# 글 프로그래밍 언어 설치 스크립트
# 사용법: irm https://raw.githubusercontent.com/wwoosshh/geul-lang/main/install.ps1 | iex

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host ""
Write-Host "  ===================================" -ForegroundColor Cyan
Write-Host "   글 프로그래밍 언어 v0.6.4 설치" -ForegroundColor Cyan
Write-Host "  ===================================" -ForegroundColor Cyan
Write-Host ""

$installDir = Join-Path $env:LOCALAPPDATA "geul-lang"
$binDir = Join-Path $installDir "bin"
$stdDir = Join-Path $installDir "std"

# 기존 설치 감지
$existing = (Test-Path (Join-Path $binDir "geulc.exe")) -or (Test-Path (Join-Path $binDir "native-compiler.exe"))

if ($existing) {
    Write-Host "  기존 설치가 감지되었습니다: $installDir" -ForegroundColor Yellow
    Write-Host ""
    $choice = Read-Host "  기존 버전을 삭제하고 새 버전으로 설치할까요? (y/n)"
    if ($choice -ne "y" -and $choice -ne "Y") {
        Write-Host ""
        Write-Host "  설치를 취소했습니다." -ForegroundColor Yellow
        Write-Host ""
        exit 0
    }
    Write-Host ""
    Write-Host "  기존 설치 제거 중..." -ForegroundColor White
    Remove-Item -Path $installDir -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "  제거 완료" -ForegroundColor Green
    Write-Host ""
}

New-Item -ItemType Directory -Path $binDir -Force | Out-Null
New-Item -ItemType Directory -Path $stdDir -Force | Out-Null

$baseUrl = "https://github.com/wwoosshh/geul-lang/releases/latest/download"

Write-Host "  [1/3] 네이티브컴파일러 다운로드 중..." -ForegroundColor White
try {
    Invoke-WebRequest -Uri "$baseUrl/native-compiler.exe" -OutFile (Join-Path $binDir "geulc.exe") -UseBasicParsing
    Write-Host "       버전: v0.6.4" -ForegroundColor Gray
    Write-Host "       완료" -ForegroundColor Green
} catch {
    Write-Host "       실패: $_" -ForegroundColor Red
    exit 1
}

Write-Host "  [2/3] 표준 라이브러리 다운로드 중..." -ForegroundColor White
try {
    Invoke-WebRequest -Uri "$baseUrl/std.gl" -OutFile (Join-Path $binDir "std.gl") -UseBasicParsing
    Write-Host "       완료" -ForegroundColor Green
} catch {
    Write-Host "       실패 (std.gl)" -ForegroundColor Yellow
}
# 개별 표준 라이브러리 파일 (GitHub raw에서 다운로드)
$stdFiles = @(
    @("core.gl", "core.gl"),
    @("io.gl", "io.gl"),
    @("string.gl", "string.gl"),
    @("memory.gl", "memory.gl"),
    @("math.gl", "math.gl"),
    @("convert.gl", "convert.gl"),
    @("time.gl", "time.gl"),
    @("system.gl", "system.gl"),
    @("hrtimer.gl", "hrtimer.gl"),
    @("list.gl", "list.gl"),
    @("error.gl", "error.gl")
)
$stdOk = 0
foreach ($entry in $stdFiles) {
    $fname = $entry[0]
    try {
        $url = "https://raw.githubusercontent.com/wwoosshh/geul-lang/main/std/$fname"
        Invoke-WebRequest -Uri $url -OutFile (Join-Path $stdDir $fname) -UseBasicParsing
        $stdOk++
    } catch { }
}
Write-Host "       표준 라이브러리: $stdOk/$($stdFiles.Count)개" -ForegroundColor $(if ($stdOk -gt 0) { "Green" } else { "Yellow" })

Write-Host "  [3/3] PATH 설정 중..." -ForegroundColor White
$userPath = [Environment]::GetEnvironmentVariable("PATH", "User")
if ($userPath -notlike "*$binDir*") {
    [Environment]::SetEnvironmentVariable("PATH", "$userPath;$binDir", "User")
    Write-Host "       PATH에 추가됨" -ForegroundColor Green
} else {
    Write-Host "       이미 설정됨" -ForegroundColor Green
}

Write-Host ""
Write-Host "  ===================================" -ForegroundColor Green
Write-Host "   설치 완료!" -ForegroundColor Green
Write-Host "  ===================================" -ForegroundColor Green
Write-Host ""
Write-Host "  설치 경로: $installDir" -ForegroundColor White
Write-Host ""
Write-Host "  사용법:" -ForegroundColor White
Write-Host "    geulc source.gl       → .exe 직접 생성 (C 불필요)" -ForegroundColor White
Write-Host ""
Write-Host "  새 터미널을 열어야 PATH가 적용됩니다." -ForegroundColor Yellow
Write-Host ""
