@echo off
chcp 65001 >nul
echo.
echo  ===================================
echo   글 프로그래밍 언어 설치
echo  ===================================
echo.

:: VS Code 확인
where code >nul 2>nul
if errorlevel 1 (
    echo  [오류] VS Code가 설치되어 있지 않습니다.
    echo  https://code.visualstudio.com 에서 먼저 설치하세요.
    echo.
    pause
    exit /b 1
)

:: 다운로드 URL (GitHub Releases에 업로드 후 변경)
set "VSIX_URL=https://github.com/wwoosshh/geul-lang/releases/latest/download/geul-language-0.5.0.vsix"
set "VSIX_FILE=%TEMP%\geul-language.vsix"

echo  [1/2] 글 확장 다운로드 중...
curl -sL -o "%VSIX_FILE%" "%VSIX_URL%"
if errorlevel 1 (
    echo  [오류] 다운로드 실패. 인터넷 연결을 확인하세요.
    pause
    exit /b 1
)

echo  [2/2] VS Code에 설치 중...
code --install-extension "%VSIX_FILE%" --force >nul 2>nul
if errorlevel 1 (
    echo  [오류] 설치 실패. VS Code를 닫고 다시 시도하세요.
    pause
    exit /b 1
)

del "%VSIX_FILE%" >nul 2>nul

echo.
echo  ===================================
echo   설치 완료!
echo  ===================================
echo.
echo  사용법:
echo    1. VS Code를 재시작하세요
echo    2. 새 파일을 만들고 .글 로 저장하세요
echo    3. 코드를 작성하고 F5를 누르면 실행됩니다
echo.
echo  예제:
echo    포함 "std.gl"
echo    [시작하기]는 {
echo        "안녕하세요!\n"을 쓰다.
echo    }
echo.
pause
