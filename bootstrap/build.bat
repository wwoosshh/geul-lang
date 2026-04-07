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
    /Fe:build\geulcc.exe ^
    src\unicode.c src\token.c src\lexer.c src\ast.c ^
    src\parser.c src\codegen.c src\llvm_gen.c src\main.c ^
    /link ^
    /LIBPATH:"%MSVC%\lib\x64" ^
    /LIBPATH:"%SDK%\Lib\10.0.26100.0\ucrt\x64" ^
    /LIBPATH:"%SDK%\Lib\10.0.26100.0\um\x64"

if %errorlevel%==0 (
    echo BUILD OK: build\geulcc.exe
    del *.obj 2>nul
) else (
    echo BUILD FAILED
    exit /b 1
)
