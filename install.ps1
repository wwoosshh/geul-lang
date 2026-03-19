# 글 프로그래밍 언어 설치 스크립트
# 사용법: irm https://raw.githubusercontent.com/geul-lang/geul/main/install.ps1 | iex

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host ""
Write-Host "  ===================================" -ForegroundColor Cyan
Write-Host "   글 프로그래밍 언어 설치" -ForegroundColor Cyan
Write-Host "  ===================================" -ForegroundColor Cyan
Write-Host ""

# VS Code 확인
$codePath = Get-Command code -ErrorAction SilentlyContinue
if (-not $codePath) {
    Write-Host "  [오류] VS Code가 설치되어 있지 않습니다." -ForegroundColor Red
    Write-Host "  https://code.visualstudio.com 에서 먼저 설치하세요." -ForegroundColor Yellow
    exit 1
}

# 다운로드
$url = "https://github.com/wwoosshh/geul-lang/releases/latest/download/geul-language-0.2.0.vsix"
$tempFile = Join-Path $env:TEMP "geul-language.vsix"

Write-Host "  [1/2] 글 확장 다운로드 중..." -ForegroundColor White
try {
    Invoke-WebRequest -Uri $url -OutFile $tempFile -UseBasicParsing
} catch {
    Write-Host "  [오류] 다운로드 실패: $_" -ForegroundColor Red
    exit 1
}

# 설치
Write-Host "  [2/2] VS Code에 설치 중..." -ForegroundColor White
& code --install-extension $tempFile --force 2>$null

Remove-Item $tempFile -Force -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "  ===================================" -ForegroundColor Green
Write-Host "   설치 완료!" -ForegroundColor Green
Write-Host "  ===================================" -ForegroundColor Green
Write-Host ""
Write-Host "  사용법:" -ForegroundColor White
Write-Host "    1. VS Code를 재시작하세요"
Write-Host "    2. 새 파일을 만들고 .글 로 저장하세요"
Write-Host "    3. 코드를 작성하고 F5를 누르면 실행됩니다"
Write-Host ""
Write-Host "  예제:" -ForegroundColor White
Write-Host '    [시작하기]는 {'
Write-Host '        "안녕하세요!\n"을 쓰기다.'
Write-Host '    }'
Write-Host ""
