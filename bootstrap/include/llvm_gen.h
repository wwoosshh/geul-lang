/*
 * llvm생성기.h - LLVM IR 코드 생성기
 *
 * 글 언어의 AST를 받아 LLVM IR 텍스트(.ll)를 생성한다.
 * C 의존성 없이 직접 네이티브 코드를 생성하기 위한 백엔드.
 *
 * 파이프라인: .글 → AST → LLVM IR (.ll) → llc → .obj → link.exe → .exe
 */
#ifndef GEUL_LLVM_CODEGEN_H
#define GEUL_LLVM_CODEGEN_H

#include "ast.h"
#include <stdio.h>

/* 최대 문자열 상수/심볼 개수 */
#define LLVM_MAX_STRINGS 512
#define LLVM_MAX_SYMBOLS 512

/* LLVM 값 표현 (SSA 임시값 또는 이름) */
#define LLVM_VAL_LEN 256

typedef struct {
    char 텍스트[LLVM_VAL_LEN];   /* "%0", "%\"가\"", "5" 등 */
    char 타입[64];                /* "i32", "double", "i8*" 등 */
} llvm_값;

/* 심볼 테이블 항목 (변수 이름 → alloca 포인터 + 타입) */
typedef struct {
    char *이름;
    char 타입[64];               /* LLVM 타입 문자열 */
} llvm_심볼;

/* 문자열 상수 항목 */
typedef struct {
    char *원본;                  /* 원본 문자열 (UTF-8) */
    int 바이트수;                /* null 포함 바이트 수 */
    int 번호;                    /* 상수 번호 (@.str.N) */
} llvm_문자열상수;

/* LLVM IR 생성기 */
typedef struct {
    FILE *출력;

    /* SSA 임시값 카운터 */
    int 임시번호;

    /* 문자열 상수 수집 */
    llvm_문자열상수 문자열[LLVM_MAX_STRINGS];
    int 문자열_수;

    /* 심볼 테이블 (현재 함수의 지역 변수) */
    llvm_심볼 심볼[LLVM_MAX_SYMBOLS];
    int 심볼_수;

    /* 현재 함수 정보 */
    bool 함수_내부;

    /* 오류 처리 */
    bool 오류_발생;
    char 오류_메시지[512];
} llvm생성기;

/* 초기화 */
void llvm_생성기_초기화(llvm생성기 *gen, FILE *출력);

/* AST로부터 LLVM IR 생성 */
bool llvm_코드_생성(llvm생성기 *gen, 노드 *프로그램);

#endif /* GEUL_LLVM_CODEGEN_H */
