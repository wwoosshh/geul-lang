cmake_minimum_required(VERSION 3.16)
project(geulcc C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)

if(MSVC)
    add_compile_options(/utf-8)
endif()

if(CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
    add_compile_options(-Wall -Wextra -finput-charset=UTF-8 -fexec-charset=UTF-8)
endif()

include_directories(include)

set(SOURCES
    src/unicode.c
    src/token.c
    src/lexer.c
    src/ast.c
    src/parser.c
    src/main.c
)

add_executable(geulcc ${SOURCES})
