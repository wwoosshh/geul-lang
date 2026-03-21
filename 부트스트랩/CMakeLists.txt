cmake_minimum_required(VERSION 3.16)
project(글cc C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)

# UTF-8 소스 파일 처리 (MSVC)
if(MSVC)
    add_compile_options(/utf-8)
endif()

# GCC/Clang UTF-8
if(CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
    add_compile_options(-Wall -Wextra -finput-charset=UTF-8 -fexec-charset=UTF-8)
endif()

# 인클루드 경로
include_directories(include)

# 소스 파일
set(SOURCES
    src/유니코드.c
    src/토큰.c
    src/형태소분석기.c
    src/구문트리.c
    src/구문분석기.c
    src/주.c
)

# 실행 파일
add_executable(글cc ${SOURCES})

# 테스트
enable_testing()
add_test(NAME 렉서_인사 COMMAND 글cc -토큰 ${CMAKE_SOURCE_DIR}/../예제/인사.글)
add_test(NAME 파서_인사 COMMAND 글cc -구문 ${CMAKE_SOURCE_DIR}/../예제/인사.글)
add_test(NAME 렉서_변수 COMMAND 글cc -토큰 ${CMAKE_SOURCE_DIR}/../예제/변수.글)
add_test(NAME 파서_변수 COMMAND 글cc -구문 ${CMAKE_SOURCE_DIR}/../예제/변수.글)
add_test(NAME 렉서_계산 COMMAND 글cc -토큰 ${CMAKE_SOURCE_DIR}/../예제/계산.글)
add_test(NAME 파서_계산 COMMAND 글cc -구문 ${CMAKE_SOURCE_DIR}/../예제/계산.글)
