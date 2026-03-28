# 글 프로그래밍 언어 설치 스크립트
# 사용법: irm https://raw.githubusercontent.com/wwoosshh/geul-lang/main/install.ps1 | iex

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host ""
Write-Host "  ===================================" -ForegroundColor Cyan
Write-Host "   글 프로그래밍 언어 v2.0 설치" -ForegroundColor Cyan
Write-Host "  ===================================" -ForegroundColor Cyan
Write-Host ""

$installDir = Join-Path $env:LOCALAPPDATA "geul-lang"
$binDir = Join-Path $installDir "bin"
$stdDir = Join-Path $installDir ([char]0xD45C + [char]0xC900)

# 기존 설치 감지
$existing = Test-Path (Join-Path $binDir ([char]0xB124 + [char]0xC774 + [char]0xD2F0 + [char]0xBE0C + [char]0xCEF4 + [char]0xD30C + [char]0xC77C + [char]0xB7EC + ".exe"))

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
$ncName = "" + [char]0xB124 + [char]0xC774 + [char]0xD2F0 + [char]0xBE0C + [char]0xCEF4 + [char]0xD30C + [char]0xC77C + [char]0xB7EC + ".exe"

Write-Host "  [1/4] 네이티브컴파일러 다운로드 중..." -ForegroundColor White
try {
    Invoke-WebRequest -Uri "$baseUrl/native-compiler.exe" -OutFile (Join-Path $binDir $ncName) -UseBasicParsing
    # 영문 복사본 (geulc.exe) — PATH/where 호환
    Copy-Item (Join-Path $binDir $ncName) (Join-Path $binDir "geulc.exe") -Force
    Write-Host "       완료" -ForegroundColor Green
} catch {
    Write-Host "       실패: $_" -ForegroundColor Red
    exit 1
}

Write-Host "  [2/4] 표준 라이브러리 다운로드 중..." -ForegroundColor White
# std.gl (통합 표준 라이브러리) — bin 디렉토리에 배치
try {
    Invoke-WebRequest -Uri "$baseUrl/std.gl" -OutFile (Join-Path $binDir "std.gl") -UseBasicParsing
} catch { }
$stdNames = @(
    ([char]0xAE30 + [char]0xBCF8),
    ([char]0xC785 + [char]0xCD9C + [char]0xB825),
    ([char]0xBB38 + [char]0xC790 + [char]0xC5F4),
    ([char]0xBA54 + [char]0xBAA8 + [char]0xB9AC),
    ([char]0xC218 + [char]0xD559),
    ([char]0xBCC0 + [char]0xD658),
    ([char]0xC2DC + [char]0xAC04),
    ([char]0xCCB4 + [char]0xACC4),
    ([char]0xC815 + [char]0xBC00 + [char]0xC2DC + [char]0xAC04)
)
$geul = "" + [char]0xAE00
$stdOk = 0
foreach ($name in $stdNames) {
    $fname = "$name.$geul"
    try {
        $url = "https://raw.githubusercontent.com/wwoosshh/geul-lang/main/" + [uri]::EscapeDataString([char]0xD45C + [char]0xC900) + "/$fname"
        Invoke-WebRequest -Uri $url -OutFile (Join-Path $stdDir $fname) -UseBasicParsing
        $stdOk++
    } catch { }
}
Write-Host "       $stdOk/${stdNames.Count}개 완료" -ForegroundColor $(if ($stdOk -gt 0) { "Green" } else { "Yellow" })

Write-Host "  [3/4] PATH 설정 중..." -ForegroundColor White
$userPath = [Environment]::GetEnvironmentVariable("PATH", "User")
if ($userPath -notlike "*$binDir*") {
    [Environment]::SetEnvironmentVariable("PATH", "$userPath;$binDir", "User")
    Write-Host "       PATH에 추가됨" -ForegroundColor Green
} else {
    Write-Host "       이미 설정됨" -ForegroundColor Green
}

$codePath = Get-Command code -ErrorAction SilentlyContinue
if ($codePath) {
    Write-Host "  [4/4] VS Code 확장 설치 중..." -ForegroundColor White
    $vsixPath = Join-Path $env:TEMP "geul-language.vsix"
    try {
        Invoke-WebRequest -Uri "$baseUrl/geul-language-0.3.1.vsix" -OutFile $vsixPath -UseBasicParsing
        & code --install-extension $vsixPath --force 2>$null
        Remove-Item $vsixPath -Force -ErrorAction SilentlyContinue
        Write-Host "       완료" -ForegroundColor Green
    } catch {
        Write-Host "       실패 (선택사항)" -ForegroundColor Yellow
    }
} else {
    Write-Host "  [4/4] VS Code 미설치 — 건너뜀" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "  ===================================" -ForegroundColor Green
Write-Host "   설치 완료!" -ForegroundColor Green
Write-Host "  ===================================" -ForegroundColor Green
Write-Host ""
Write-Host "  설치 경로: $installDir" -ForegroundColor White
Write-Host ""
Write-Host "  사용법:" -ForegroundColor White
Write-Host "    네이티브컴파일러 소스.$geul       → .exe 직접 생성 (C 불필요)" -ForegroundColor White
Write-Host ""
Write-Host "  VS Code: .$geul 파일 만들고 편집 → 터미널에서 컴파일" -ForegroundColor White
$msg = "  " + [char]0xC0C8 + " " + [char]0xD130 + [char]0xBBF8 + [char]0xB110 + [char]0xC744 + " " + [char]0xC5F4 + [char]0xC5B4 + [char]0xC57C + " PATH" + [char]0xAC00 + " " + [char]0xC801 + [char]0xC6A9 + [char]0xB429 + [char]0xB2C8 + [char]0xB2E4 + "."
Write-Host $msg -ForegroundColor Yellow
Write-Host ""
