# 글 프로그래밍 언어 설치 스크립트
# 사용법: irm https://raw.githubusercontent.com/wwoosshh/geul-lang/main/install.ps1 | iex

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host ""
Write-Host "  ===================================" -ForegroundColor Cyan
Write-Host "   글 프로그래밍 언어 v1.0 설치" -ForegroundColor Cyan
Write-Host "  ===================================" -ForegroundColor Cyan
Write-Host ""

$installDir = Join-Path $env:LOCALAPPDATA "geul-lang"
$binDir = Join-Path $installDir "bin"
$stdDir = Join-Path $installDir "표준"
New-Item -ItemType Directory -Path $binDir -Force | Out-Null
New-Item -ItemType Directory -Path $stdDir -Force | Out-Null

$baseUrl = "https://github.com/wwoosshh/geul-lang/releases/latest/download"

Write-Host "  [1/5] 글도구.exe 다운로드 중..." -ForegroundColor White
try { Invoke-WebRequest -Uri "$baseUrl/geultool.exe" -OutFile (Join-Path $binDir "글도구.exe") -UseBasicParsing }
catch { Write-Host "  [경고] 다운로드 실패" -ForegroundColor Yellow }

Write-Host "  [2/5] 네이티브컴파일러.exe 다운로드 중..." -ForegroundColor White
try { Invoke-WebRequest -Uri "$baseUrl/native-compiler.exe" -OutFile (Join-Path $binDir "네이티브컴파일러.exe") -UseBasicParsing }
catch { Write-Host "  [경고] 다운로드 실패" -ForegroundColor Yellow }

Write-Host "  [3/5] 표준 라이브러리 다운로드 중..." -ForegroundColor White
$stdFiles = @("기본.글","입출력.글","문자열.글","메모리.글","수학.글","변환.글","시간.글","체계.글","정밀시간.글")
foreach ($f in $stdFiles) {
    try { Invoke-WebRequest -Uri "https://raw.githubusercontent.com/wwoosshh/geul-lang/main/표준/$f" -OutFile (Join-Path $stdDir $f) -UseBasicParsing } catch { }
}

Write-Host "  [4/5] PATH 설정 중..." -ForegroundColor White
$userPath = [Environment]::GetEnvironmentVariable("PATH", "User")
if ($userPath -notlike "*$binDir*") {
    [Environment]::SetEnvironmentVariable("PATH", "$userPath;$binDir", "User")
}

$codePath = Get-Command code -ErrorAction SilentlyContinue
if ($codePath) {
    Write-Host "  [5/5] VS Code 확장 설치 중..." -ForegroundColor White
    $vsixPath = Join-Path $env:TEMP "geul-language.vsix"
    try {
        Invoke-WebRequest -Uri "$baseUrl/geul-language-0.2.0.vsix" -OutFile $vsixPath -UseBasicParsing
        & code --install-extension $vsixPath --force 2>$null
        Remove-Item $vsixPath -Force -ErrorAction SilentlyContinue
    } catch { Write-Host "  [경고] 확장 설치 실패" -ForegroundColor Yellow }
} else {
    Write-Host "  [5/5] VS Code 미설치 — 건너뜀" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "  ===================================" -ForegroundColor Green
Write-Host "   설치 완료!" -ForegroundColor Green
Write-Host "  ===================================" -ForegroundColor Green
Write-Host ""
Write-Host "  설치 경로: $installDir"
Write-Host ""
Write-Host "  사용법:"
Write-Host "    글도구 실행 소스.글           # C 트랜스파일 (MSVC 필요)"
Write-Host "    네이티브컴파일러 소스.글       # 네이티브 .exe 직접 생성"
Write-Host ""
Write-Host "  VS Code: .글 파일 만들고 F5 → 실행"
Write-Host "  새 터미널을 열어야 PATH가 적용됩니다." -ForegroundColor Yellow
Write-Host ""
