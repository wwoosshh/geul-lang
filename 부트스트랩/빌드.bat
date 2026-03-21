@echo off
chcp 65001 >nul
echo === 글 컴파일러 빌드 ===

if not exist build mkdir build

set SRCS=src\유니코드.c src\토큰.c src\형태소분석기.c src\구문트리.c src\구문분석기.c src\코드생성기.c src\llvm생성기.c src\주.c

REM MSVC (Visual Studio 2022) 직접 경로
set MSVC_BIN=C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC\14.44.35207\bin\Hostx64\x64
set MSVC_INC=C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC\14.44.35207\include
set UCRT_INC=C:\Program Files (x86)\Windows Kits\10\Include\10.0.26100.0\ucrt
set UM_INC=C:\Program Files (x86)\Windows Kits\10\Include\10.0.26100.0\um
set SHARED_INC=C:\Program Files (x86)\Windows Kits\10\Include\10.0.26100.0\shared
set MSVC_LIB=C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC\14.44.35207\lib\x64
set UCRT_LIB=C:\Program Files (x86)\Windows Kits\10\Lib\10.0.26100.0\ucrt\x64
set UM_LIB=C:\Program Files (x86)\Windows Kits\10\Lib\10.0.26100.0\um\x64

echo MSVC로 빌드합니다...
"%MSVC_BIN%\cl.exe" /utf-8 /nologo /std:c11 /W3 /Iinclude /I"%MSVC_INC%" /I"%UCRT_INC%" /I"%UM_INC%" /I"%SHARED_INC%" /Fe:build\글cc.exe %SRCS% /link /LIBPATH:"%MSVC_LIB%" /LIBPATH:"%UCRT_LIB%" /LIBPATH:"%UM_LIB%"
if %errorlevel%==0 (
    echo 빌드 성공: build\글cc.exe
    del *.obj 2>nul
) else (
    echo 빌드 실패
    exit /b 1
)
