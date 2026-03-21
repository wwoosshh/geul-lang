@echo off
chcp 65001 >nul

if not exist build mkdir build

set "MSVC=C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC\14.44.35207"
set "SDK=C:\Program Files (x86)\Windows Kits\10"

"%MSVC%\bin\Hostx64\x64\cl.exe" /utf-8 /nologo /std:c11 /W3 ^
    /Iinclude ^
    /I"%MSVC%\include" ^
    /I"%SDK%\Include\10.0.26100.0\ucrt" ^
    /I"%SDK%\Include\10.0.26100.0\um" ^
    /I"%SDK%\Include\10.0.26100.0\shared" ^
    /Fe:build\글cc.exe ^
    src\유니코드.c src\토큰.c src\형태소분석기.c src\구문트리.c ^
    src\구문분석기.c src\코드생성기.c src\llvm생성기.c src\주.c ^
    /link ^
    /LIBPATH:"%MSVC%\lib\x64" ^
    /LIBPATH:"%SDK%\Lib\10.0.26100.0\ucrt\x64" ^
    /LIBPATH:"%SDK%\Lib\10.0.26100.0\um\x64"

if %errorlevel%==0 (
    echo BUILD OK: build\글cc.exe
    del *.obj 2>nul
) else (
    echo BUILD FAILED
    exit /b 1
)
