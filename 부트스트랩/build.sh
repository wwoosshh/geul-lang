#!/bin/bash
# 글 컴파일러 빌드 스크립트 (Git Bash + MSVC)

cd "$(dirname "$0")"
mkdir -p build

MSVC_W='C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC\14.44.35207'
SDK_W='C:\Program Files (x86)\Windows Kits\10'
CL="/c/Program Files/Microsoft Visual Studio/2022/Community/VC/Tools/MSVC/14.44.35207/bin/Hostx64/x64/cl.exe"

export INCLUDE="${MSVC_W}\\include;${SDK_W}\\Include\\10.0.26100.0\\ucrt;${SDK_W}\\Include\\10.0.26100.0\\um;${SDK_W}\\Include\\10.0.26100.0\\shared"
export LIB="${MSVC_W}\\lib\\x64;${SDK_W}\\Lib\\10.0.26100.0\\ucrt\\x64;${SDK_W}\\Lib\\10.0.26100.0\\um\\x64"

SRCS="src/유니코드.c src/토큰.c src/형태소분석기.c src/구문트리.c src/구문분석기.c src/코드생성기.c src/llvm생성기.c src/주.c"

echo "=== 글 컴파일러 빌드 ==="

MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL="*" \
    "$CL" /utf-8 /nologo /std:c11 /W3 /Iinclude \
    /Fe:build/글cc.exe $SRCS \
    /link

if [ $? -eq 0 ]; then
    echo "BUILD OK: build/글cc.exe"
    rm -f *.obj
else
    echo "BUILD FAILED"
    exit 1
fi
