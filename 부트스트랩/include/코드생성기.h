/*
 * 코드생성기.h - C 코드 생성기
 *
 * 글 언어의 AST를 받아 C11 소스 코드를 생성한다.
 */
#ifndef GEUL_CODEGEN_H
#define GEUL_CODEGEN_H

#include "구문트리.h"
#include <stdio.h>

typedef struct {
    FILE *출력;          /* output C file */
    int 들여쓰기_깊이;
    int 임시변수_번호;   /* for generating temp var names */
    bool 오류_발생;
    char 오류_메시지[512];

    /* 나열(enum) 타입 이름 등록 (struct와 구분) */
    char *나열이름목록[128];
    int 나열이름_수;

    /* 별칭(typedef) 타입 이름 등록 (struct 접두사 제거) */
    char *별칭이름목록[128];
    int 별칭이름_수;

    /* 합침(union) 타입 이름 등록 (struct 대신 union 사용) */
    char *합침이름목록[128];
    int 합침이름_수;
} 코드생성기;

/* Initialize code generator */
void 생성기_초기화(코드생성기 *gen, FILE *출력);

/* Generate C code from AST */
bool 코드_생성(코드생성기 *gen, 노드 *프로그램);

#endif /* GEUL_CODEGEN_H */
