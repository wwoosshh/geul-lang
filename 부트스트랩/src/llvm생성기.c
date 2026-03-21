/*
 * llvm생성기.c - LLVM IR 텍스트 생성기 구현
 *
 * 글 언어의 AST를 순회하며 LLVM IR (.ll) 파일을 생성한다.
 * 생성된 IR은 llc로 오브젝트 파일로 컴파일하고,
 * 시스템 링커(link.exe)로 네이티브 실행 파일을 만든다.
 *
 * C 코드를 거치지 않고 직접 네이티브 코드를 생성하므로
 * C 컴파일러 의존성이 완전히 제거된다.
 */

#include "llvm생성기.h"
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>

/* ===== 유틸리티 ===== */

static void 오류(llvm생성기 *gen, const char *형식, ...) {
    va_list ap;
    va_start(ap, 형식);
    vsnprintf(gen->오류_메시지, sizeof(gen->오류_메시지), 형식, ap);
    va_end(ap);
    gen->오류_발생 = true;
}

static void 출력(llvm생성기 *gen, const char *형식, ...) {
    va_list ap;
    va_start(ap, 형식);
    vfprintf(gen->출력, 형식, ap);
    va_end(ap);
}

/* 새 임시값 번호를 할당하고 "%N" 형태의 문자열을 반환 */
static int 새_임시(llvm생성기 *gen) {
    return gen->임시번호++;
}

/* ===== LLVM 타입 매핑 ===== */

/* AST 타입 노드를 LLVM IR 타입 문자열로 변환 */
static const char *타입_변환(노드 *타입) {
    if (!타입) return "void";

    switch (타입->종류) {
    case 노드_기본타입:
        switch (타입->데이터.기본타입.기본) {
        case 토큰_정수:       return "i32";
        case 토큰_긴정수:     return "i64";
        case 토큰_짧은정수:   return "i16";
        case 토큰_작은정수:   return "i8";
        case 토큰_부호없는:   return "i32";
        case 토큰_실수:       return "double";
        case 토큰_짧은실수:   return "float";
        case 토큰_문자:       return "i8";
        case 토큰_문자열:     return "i8*";
        case 토큰_참거짓:     return "i1";
        case 토큰_공허:       return "void";
        default:              return "i32";
        }
    case 노드_참조타입:
        return "i8*"; /* 단순화: 모든 포인터를 i8*로 */
    case 노드_배열타입:
        return "i8*"; /* 단순화 */
    case 노드_묶음타입명:
        return "i8*"; /* 단순화 */
    default:
        return "i32";
    }
}

/* ===== 이름 이스케이핑 ===== */

/* 한글 식별자를 LLVM IR용 이름으로 변환 */
/* 시작하기 → main, 그 외 → @"이름" */
static void 함수이름_출력(llvm생성기 *gen, const char *이름) {
    if (strcmp(이름, "시작하기") == 0) {
        출력(gen, "@main");
    } else {
        출력(gen, "@\"%s\"", 이름);
    }
}

static void 지역이름_출력(llvm생성기 *gen, const char *이름) {
    출력(gen, "%%\"%s\"", 이름);
}

/* ===== 심볼 테이블 ===== */

static void 심볼_초기화(llvm생성기 *gen) {
    gen->심볼_수 = 0;
}

static void 심볼_추가(llvm생성기 *gen, const char *이름, const char *타입) {
    if (gen->심볼_수 >= LLVM_MAX_SYMBOLS) return;
    llvm_심볼 *s = &gen->심볼[gen->심볼_수++];
    s->이름 = strdup(이름);
    strncpy(s->타입, 타입, sizeof(s->타입) - 1);
    s->타입[sizeof(s->타입) - 1] = '\0';
}

static const char *심볼_타입_찾기(llvm생성기 *gen, const char *이름) {
    for (int i = gen->심볼_수 - 1; i >= 0; i--) {
        if (strcmp(gen->심볼[i].이름, 이름) == 0) {
            return gen->심볼[i].타입;
        }
    }
    return "i32"; /* 기본값 */
}

static void 심볼_해제(llvm생성기 *gen) {
    for (int i = 0; i < gen->심볼_수; i++) {
        free(gen->심볼[i].이름);
    }
    gen->심볼_수 = 0;
}

/* ===== 문자열 상수 수집 ===== */

/* 문자열을 LLVM IR 바이트 배열 형식으로 출력
 * 한글(UTF-8 >= 0x80)은 \XX 이스케이프, ASCII는 그대로 */
static int 문자열_바이트수(const char *s) {
    return (int)strlen(s) + 1; /* null terminator 포함 */
}

static void 문자열_바이트_출력(llvm생성기 *gen, const char *s) {
    출력(gen, "c\"");
    const unsigned char *p = (const unsigned char *)s;
    while (*p) {
        if (*p >= 0x20 && *p < 0x7F && *p != '"' && *p != '\\') {
            출력(gen, "%c", *p);
        } else {
            출력(gen, "\\%02X", *p);
        }
        p++;
    }
    출력(gen, "\\00\""); /* null terminator */
}

/* 문자열 상수를 등록하고 번호를 반환 */
static int 문자열_상수_등록(llvm생성기 *gen, const char *값) {
    /* 이미 등록된 것이 있는지 확인 */
    for (int i = 0; i < gen->문자열_수; i++) {
        if (strcmp(gen->문자열[i].원본, 값) == 0) {
            return gen->문자열[i].번호;
        }
    }

    if (gen->문자열_수 >= LLVM_MAX_STRINGS) return -1;

    int 번호 = gen->문자열_수;
    llvm_문자열상수 *sc = &gen->문자열[gen->문자열_수++];
    sc->원본 = strdup(값);
    sc->바이트수 = 문자열_바이트수(값);
    sc->번호 = 번호;
    return 번호;
}

/* ===== 전방 선언 ===== */

static llvm_값 생성_표현식(llvm생성기 *gen, 노드 *n);
static void 생성_문장(llvm생성기 *gen, 노드 *n);

/* 사용자 외부 선언 추적 (중복 방지) */
static const char *사용자_외부선언[128];
static int 사용자_외부선언_수 = 0;

static bool 외부선언_존재(const char *이름) {
    for (int i = 0; i < 사용자_외부선언_수; i++) {
        if (strcmp(사용자_외부선언[i], 이름) == 0) return true;
    }
    return false;
}

/* ===== 표현식 생성 ===== */

/* 정수 리터럴 */
static llvm_값 생성_정수_리터럴(llvm생성기 *gen, 노드 *n) {
    llvm_값 결과;
    snprintf(결과.텍스트, LLVM_VAL_LEN, "%lld", n->데이터.정수_리터럴.값);
    strcpy(결과.타입, "i32");
    return 결과;
}

/* 실수 리터럴 */
static llvm_값 생성_실수_리터럴(llvm생성기 *gen, 노드 *n) {
    llvm_값 결과;
    snprintf(결과.텍스트, LLVM_VAL_LEN, "%e", n->데이터.실수_리터럴.값);
    strcpy(결과.타입, "double");
    return 결과;
}

/* 문자열 리터럴 */
static llvm_값 생성_문자열_리터럴(llvm생성기 *gen, 노드 *n) {
    const char *문자열값 = n->데이터.문자열_리터럴.값;
    int 번호 = 문자열_상수_등록(gen, 문자열값);
    int 바이트수 = 문자열_바이트수(문자열값);

    llvm_값 결과;
    int t = 새_임시(gen);
    출력(gen, "    %%%d = getelementptr inbounds [%d x i8], [%d x i8]* @.str.%d, i64 0, i64 0\n",
         t, 바이트수, 바이트수, 번호);
    snprintf(결과.텍스트, LLVM_VAL_LEN, "%%%d", t);
    strcpy(결과.타입, "i8*");
    return 결과;
}

/* 참거짓 리터럴 */
static llvm_값 생성_참거짓_리터럴(llvm생성기 *gen, 노드 *n) {
    llvm_값 결과;
    snprintf(결과.텍스트, LLVM_VAL_LEN, "%d", n->데이터.참거짓_리터럴.값 ? 1 : 0);
    strcpy(결과.타입, "i1");
    return 결과;
}

/* 없음 리터럴 */
static llvm_값 생성_없음_리터럴(llvm생성기 *gen) {
    llvm_값 결과;
    strcpy(결과.텍스트, "null");
    strcpy(결과.타입, "i8*");
    return 결과;
}

/* 식별자 (변수 읽기) */
static llvm_값 생성_식별자(llvm생성기 *gen, 노드 *n) {
    const char *이름 = n->데이터.식별자.이름;
    const char *타입 = 심볼_타입_찾기(gen, 이름);

    llvm_값 결과;
    int t = 새_임시(gen);
    출력(gen, "    %%%d = load %s, %s* %%\"%s\"\n", t, 타입, 타입, 이름);
    snprintf(결과.텍스트, LLVM_VAL_LEN, "%%%d", t);
    strncpy(결과.타입, 타입, sizeof(결과.타입) - 1);
    return 결과;
}

/* 이항 연산 */
static llvm_값 생성_이항연산(llvm생성기 *gen, 노드 *n) {
    llvm_값 왼쪽 = 생성_표현식(gen, n->데이터.이항연산.왼쪽);
    llvm_값 오른쪽 = 생성_표현식(gen, n->데이터.이항연산.오른쪽);

    const char *명령;
    bool 비교 = false;
    const char *비교_조건 = NULL;

    bool 실수연산 = (strcmp(왼쪽.타입, "double") == 0 || strcmp(왼쪽.타입, "float") == 0);

    switch (n->데이터.이항연산.연산자) {
    case 토큰_더하기:      명령 = 실수연산 ? "fadd" : "add"; break;
    case 토큰_빼기:        명령 = 실수연산 ? "fsub" : "sub"; break;
    case 토큰_곱하기:      명령 = 실수연산 ? "fmul" : "mul"; break;
    case 토큰_나누기:      명령 = 실수연산 ? "fdiv" : "sdiv"; break;
    case 토큰_나머지:      명령 = 실수연산 ? "frem" : "srem"; break;
    case 토큰_같다:        비교 = true; 비교_조건 = 실수연산 ? "oeq" : "eq"; break;
    case 토큰_다르다:      비교 = true; 비교_조건 = 실수연산 ? "one" : "ne"; break;
    case 토큰_크다:        비교 = true; 비교_조건 = 실수연산 ? "ogt" : "sgt"; break;
    case 토큰_작다:        비교 = true; 비교_조건 = 실수연산 ? "olt" : "slt"; break;
    case 토큰_크거나같다:  비교 = true; 비교_조건 = 실수연산 ? "oge" : "sge"; break;
    case 토큰_작거나같다:  비교 = true; 비교_조건 = 실수연산 ? "ole" : "sle"; break;
    case 토큰_비트와:      명령 = "and"; break;
    case 토큰_비트또는:    명령 = "or"; break;
    case 토큰_비트배타:    명령 = "xor"; break;
    case 토큰_왼쪽이동:    명령 = "shl"; break;
    case 토큰_오른쪽이동:  명령 = "ashr"; break;
    case 토큰_그리고:      명령 = "and"; break;
    case 토큰_또는:        명령 = "or"; break;
    default:
        명령 = "add";
        오류(gen, "알 수 없는 이항 연산자");
        break;
    }

    llvm_값 결과;
    int t = 새_임시(gen);

    if (비교) {
        if (실수연산) {
            출력(gen, "    %%%d = fcmp %s %s %s, %s\n",
                 t, 비교_조건, 왼쪽.타입, 왼쪽.텍스트, 오른쪽.텍스트);
        } else {
            출력(gen, "    %%%d = icmp %s %s %s, %s\n",
                 t, 비교_조건, 왼쪽.타입, 왼쪽.텍스트, 오른쪽.텍스트);
        }
        snprintf(결과.텍스트, LLVM_VAL_LEN, "%%%d", t);
        strcpy(결과.타입, "i1");
    } else {
        출력(gen, "    %%%d = %s %s %s, %s\n",
             t, 명령, 왼쪽.타입, 왼쪽.텍스트, 오른쪽.텍스트);
        snprintf(결과.텍스트, LLVM_VAL_LEN, "%%%d", t);
        strcpy(결과.타입, 왼쪽.타입);
    }

    return 결과;
}

/* 단항 연산 */
static llvm_값 생성_단항연산(llvm생성기 *gen, 노드 *n) {
    llvm_값 피연산자 = 생성_표현식(gen, n->데이터.단항연산.피연산자);
    llvm_값 결과;
    int t = 새_임시(gen);

    switch (n->데이터.단항연산.연산자) {
    case 토큰_빼기:
        출력(gen, "    %%%d = sub %s 0, %s\n", t, 피연산자.타입, 피연산자.텍스트);
        break;
    case 토큰_아닌:
        출력(gen, "    %%%d = icmp eq %s %s, 0\n", t, 피연산자.타입, 피연산자.텍스트);
        strcpy(피연산자.타입, "i1");
        break;
    case 토큰_비트아닌:
        출력(gen, "    %%%d = xor %s %s, -1\n", t, 피연산자.타입, 피연산자.텍스트);
        break;
    default:
        출력(gen, "    %%%d = add %s %s, 0\n", t, 피연산자.타입, 피연산자.텍스트);
        break;
    }

    snprintf(결과.텍스트, LLVM_VAL_LEN, "%%%d", t);
    strcpy(결과.타입, 피연산자.타입);
    return 결과;
}

/* 함수 호출 생성 */
static llvm_값 생성_호출(llvm생성기 *gen, 노드 *n) {
    const char *함수이름 = n->데이터.호출.함수이름;
    llvm_값 결과;
    결과.텍스트[0] = '\0';
    strcpy(결과.타입, "void");

    /* 특수 내장 함수: 출력 */
    if (strcmp(함수이름, "출력") == 0) {
        인자 *인자p = n->데이터.호출.인자목록;
        if (!인자p) return 결과;

        llvm_값 인자값 = 생성_표현식(gen, 인자p->값);

        if (strcmp(인자값.타입, "i8*") == 0) {
            /* 문자열 출력: puts(str) */
            int t = 새_임시(gen);
            출력(gen, "    %%%d = call i32 @puts(i8* %s)\n", t, 인자값.텍스트);
            snprintf(결과.텍스트, LLVM_VAL_LEN, "%%%d", t);
            strcpy(결과.타입, "i32");
        } else if (strcmp(인자값.타입, "i32") == 0) {
            /* 정수 출력: printf("%d\n", val) */
            int t1 = 새_임시(gen);
            출력(gen, "    %%%d = getelementptr inbounds [4 x i8], [4 x i8]* @.fmt.int, i64 0, i64 0\n", t1);
            int t2 = 새_임시(gen);
            출력(gen, "    %%%d = call i32 (i8*, ...) @printf(i8* %%%d, i32 %s)\n",
                 t2, t1, 인자값.텍스트);
            snprintf(결과.텍스트, LLVM_VAL_LEN, "%%%d", t2);
            strcpy(결과.타입, "i32");
        } else if (strcmp(인자값.타입, "i64") == 0) {
            int t1 = 새_임시(gen);
            출력(gen, "    %%%d = getelementptr inbounds [6 x i8], [6 x i8]* @.fmt.long, i64 0, i64 0\n", t1);
            int t2 = 새_임시(gen);
            출력(gen, "    %%%d = call i32 (i8*, ...) @printf(i8* %%%d, i64 %s)\n",
                 t2, t1, 인자값.텍스트);
            snprintf(결과.텍스트, LLVM_VAL_LEN, "%%%d", t2);
            strcpy(결과.타입, "i32");
        } else if (strcmp(인자값.타입, "double") == 0 || strcmp(인자값.타입, "float") == 0) {
            int t1 = 새_임시(gen);
            출력(gen, "    %%%d = getelementptr inbounds [4 x i8], [4 x i8]* @.fmt.double, i64 0, i64 0\n", t1);
            int t2 = 새_임시(gen);
            출력(gen, "    %%%d = call i32 (i8*, ...) @printf(i8* %%%d, double %s)\n",
                 t2, t1, 인자값.텍스트);
            snprintf(결과.텍스트, LLVM_VAL_LEN, "%%%d", t2);
            strcpy(결과.타입, "i32");
        } else {
            /* 기본: 정수로 출력 */
            int t1 = 새_임시(gen);
            출력(gen, "    %%%d = getelementptr inbounds [4 x i8], [4 x i8]* @.fmt.int, i64 0, i64 0\n", t1);
            int t2 = 새_임시(gen);
            출력(gen, "    %%%d = call i32 (i8*, ...) @printf(i8* %%%d, i32 %s)\n",
                 t2, t1, 인자값.텍스트);
            snprintf(결과.텍스트, LLVM_VAL_LEN, "%%%d", t2);
            strcpy(결과.타입, "i32");
        }
        return 결과;
    }

    /* 일반 사용자 함수 호출 */
    /* 인자 값들을 먼저 생성 */
    llvm_값 인자값들[16];
    int 인자수 = 0;
    인자 *인자p = n->데이터.호출.인자목록;
    while (인자p && 인자수 < 16) {
        인자값들[인자수] = 생성_표현식(gen, 인자p->값);
        인자수++;
        인자p = 인자p->다음;
    }

    /* 함수 반환 타입 조회 (심볼 테이블에서) - 기본값 i32 */
    const char *반환타입 = 심볼_타입_찾기(gen, 함수이름);

    /* 외부 선언 함수인지 확인 (가변인자 여부) */
    bool 가변 = 외부선언_존재(함수이름);

    int t = 새_임시(gen);
    if (strcmp(반환타입, "void") == 0) {
        출력(gen, "    call void ");
        if (가변) 출력(gen, "@%s(", 함수이름);
        else { 함수이름_출력(gen, 함수이름); 출력(gen, "("); }
    } else {
        if (가변) {
            /* 가변인자 함수: call 반환타입 (인자타입, ...) @이름(...) */
            출력(gen, "    %%%d = call %s (i8*, ...) @%s(", t, 반환타입, 함수이름);
        } else {
            출력(gen, "    %%%d = call %s ", t, 반환타입);
            함수이름_출력(gen, 함수이름);
            출력(gen, "(");
        }
    }

    for (int i = 0; i < 인자수; i++) {
        if (i > 0) 출력(gen, ", ");
        출력(gen, "%s %s", 인자값들[i].타입, 인자값들[i].텍스트);
    }
    출력(gen, ")\n");

    snprintf(결과.텍스트, LLVM_VAL_LEN, "%%%d", t);
    strncpy(결과.타입, 반환타입, sizeof(결과.타입) - 1);
    return 결과;
}

/* 멤버 접근 */
static llvm_값 생성_멤버접근(llvm생성기 *gen, 노드 *n) {
    /* 단순화: 묶음을 i8* 포인터로 취급하고 GEP로 접근 */
    llvm_값 대상 = 생성_표현식(gen, n->데이터.멤버접근.대상);
    llvm_값 결과;
    /* TODO: 묶음 타입 정보로 실제 오프셋 계산 */
    /* 현재는 단순화하여 대상 자체를 반환 */
    snprintf(결과.텍스트, LLVM_VAL_LEN, "%s", 대상.텍스트);
    strcpy(결과.타입, 대상.타입);
    return 결과;
}

/* 배열 접근 */
static llvm_값 생성_배열접근(llvm생성기 *gen, 노드 *n) {
    llvm_값 배열 = 생성_표현식(gen, n->데이터.배열접근.배열);
    llvm_값 인덱스 = 생성_표현식(gen, n->데이터.배열접근.인덱스);

    llvm_값 결과;
    int t_ptr = 새_임시(gen);
    /* 배열은 i8* (포인터)로 취급 - GEP로 오프셋 계산 */
    출력(gen, "    %%%d = getelementptr i8, i8* %s, %s %s\n",
         t_ptr, 배열.텍스트, 인덱스.타입, 인덱스.텍스트);

    int t_val = 새_임시(gen);
    출력(gen, "    %%%d = load i8, i8* %%%d\n", t_val, t_ptr);

    snprintf(결과.텍스트, LLVM_VAL_LEN, "%%%d", t_val);
    strcpy(결과.타입, "i8");
    return 결과;
}

/* 주소참조 (&) */
static llvm_값 생성_주소참조(llvm생성기 *gen, 노드 *n) {
    llvm_값 결과;
    /* 식별자의 alloca 주소를 반환 */
    if (n->데이터.참조연산.대상->종류 == 노드_식별자) {
        const char *이름 = n->데이터.참조연산.대상->데이터.식별자.이름;
        snprintf(결과.텍스트, LLVM_VAL_LEN, "%%\"%s\"", 이름);
        const char *원본타입 = 심볼_타입_찾기(gen, 이름);
        snprintf(결과.타입, sizeof(결과.타입), "%s*", 원본타입);
    } else {
        오류(gen, "주소참조(&)는 식별자에만 사용 가능합니다");
        strcpy(결과.텍스트, "null");
        strcpy(결과.타입, "i8*");
    }
    return 결과;
}

/* 역참조 (*) */
static llvm_값 생성_역참조(llvm생성기 *gen, 노드 *n) {
    llvm_값 포인터 = 생성_표현식(gen, n->데이터.참조연산.대상);
    llvm_값 결과;
    int t = 새_임시(gen);
    /* 포인터 타입에서 * 제거 → 값 타입 */
    char 값타입[64];
    size_t len = strlen(포인터.타입);
    if (len > 1 && 포인터.타입[len-1] == '*') {
        strncpy(값타입, 포인터.타입, len - 1);
        값타입[len-1] = '\0';
    } else {
        strcpy(값타입, "i8");
    }
    출력(gen, "    %%%d = load %s, %s %s\n", t, 값타입, 포인터.타입, 포인터.텍스트);
    snprintf(결과.텍스트, LLVM_VAL_LEN, "%%%d", t);
    strcpy(결과.타입, 값타입);
    return 결과;
}

/* 형변환 */
static llvm_값 생성_형변환(llvm생성기 *gen, 노드 *n) {
    llvm_값 값 = 생성_표현식(gen, n->데이터.형변환.값);
    const char *대상타입 = 타입_변환(n->데이터.형변환.대상타입);
    llvm_값 결과;

    if (strcmp(값.타입, 대상타입) == 0) {
        return 값; /* 같은 타입이면 변환 불필요 */
    }

    int t = 새_임시(gen);
    bool 원본_실수 = (strcmp(값.타입, "double") == 0 || strcmp(값.타입, "float") == 0);
    bool 대상_실수 = (strcmp(대상타입, "double") == 0 || strcmp(대상타입, "float") == 0);

    if (원본_실수 && !대상_실수) {
        출력(gen, "    %%%d = fptosi %s %s to %s\n", t, 값.타입, 값.텍스트, 대상타입);
    } else if (!원본_실수 && 대상_실수) {
        출력(gen, "    %%%d = sitofp %s %s to %s\n", t, 값.타입, 값.텍스트, 대상타입);
    } else if (원본_실수 && 대상_실수) {
        if (strcmp(값.타입, "float") == 0)
            출력(gen, "    %%%d = fpext %s %s to %s\n", t, 값.타입, 값.텍스트, 대상타입);
        else
            출력(gen, "    %%%d = fptrunc %s %s to %s\n", t, 값.타입, 값.텍스트, 대상타입);
    } else {
        /* 정수 간 변환 */
        출력(gen, "    %%%d = sext %s %s to %s\n", t, 값.타입, 값.텍스트, 대상타입);
    }

    snprintf(결과.텍스트, LLVM_VAL_LEN, "%%%d", t);
    strcpy(결과.타입, 대상타입);
    return 결과;
}

/* 크기 연산 (sizeof) */
static llvm_값 생성_크기(llvm생성기 *gen, 노드 *n) {
    llvm_값 결과;
    /* GEP trick: sizeof(타입) = getelementptr 타입, 타입* null, i32 1 → ptrtoint */
    const char *타입 = 타입_변환(n->데이터.크기연산.대상);
    int t1 = 새_임시(gen);
    출력(gen, "    %%%d = getelementptr %s, %s* null, i32 1\n", t1, 타입, 타입);
    int t2 = 새_임시(gen);
    출력(gen, "    %%%d = ptrtoint %s* %%%d to i32\n", t2, 타입, t1);
    snprintf(결과.텍스트, LLVM_VAL_LEN, "%%%d", t2);
    strcpy(결과.타입, "i32");
    return 결과;
}

/* 표현식 디스패치 */
static llvm_값 생성_표현식(llvm생성기 *gen, 노드 *n) {
    llvm_값 빈값 = { "0", "i32" };
    if (!n || gen->오류_발생) return 빈값;

    switch (n->종류) {
    case 노드_정수_리터럴:     return 생성_정수_리터럴(gen, n);
    case 노드_실수_리터럴:     return 생성_실수_리터럴(gen, n);
    case 노드_문자열_리터럴:   return 생성_문자열_리터럴(gen, n);
    case 노드_참거짓_리터럴:   return 생성_참거짓_리터럴(gen, n);
    case 노드_없음_리터럴:     return 생성_없음_리터럴(gen);
    case 노드_식별자:          return 생성_식별자(gen, n);
    case 노드_이항연산:        return 생성_이항연산(gen, n);
    case 노드_단항연산:        return 생성_단항연산(gen, n);
    case 노드_호출:            return 생성_호출(gen, n);
    case 노드_멤버접근:        return 생성_멤버접근(gen, n);
    case 노드_배열접근:        return 생성_배열접근(gen, n);
    case 노드_주소참조:        return 생성_주소참조(gen, n);
    case 노드_역참조:          return 생성_역참조(gen, n);
    case 노드_형변환:          return 생성_형변환(gen, n);
    case 노드_크기:            return 생성_크기(gen, n);
    default:
        오류(gen, "지원하지 않는 표현식 노드: %d", n->종류);
        return 빈값;
    }
}

/* ===== 문장 생성 ===== */

/* 변수 선언 */
static void 생성_변수선언(llvm생성기 *gen, 노드 *n) {
    const char *이름 = n->데이터.변수선언.이름;
    const char *타입 = 타입_변환(n->데이터.변수선언.타입);

    /* alloca로 스택 공간 확보 */
    출력(gen, "    %%\"%s\" = alloca %s\n", 이름, 타입);

    /* 심볼 테이블에 등록 */
    심볼_추가(gen, 이름, 타입);

    /* 초기값이 있으면 store */
    if (n->데이터.변수선언.초기값) {
        llvm_값 초기값 = 생성_표현식(gen, n->데이터.변수선언.초기값);
        출력(gen, "    store %s %s, %s* %%\"%s\"\n",
             타입, 초기값.텍스트, 타입, 이름);
    }
}

/* 반환문 */
static void 생성_반환문(llvm생성기 *gen, 노드 *n) {
    if (n->데이터.반환문.값) {
        llvm_값 값 = 생성_표현식(gen, n->데이터.반환문.값);
        출력(gen, "    ret %s %s\n", 값.타입, 값.텍스트);
    } else {
        출력(gen, "    ret void\n");
    }
}

/* 조건문 */
static void 생성_조건문(llvm생성기 *gen, 노드 *n) {
    llvm_값 조건 = 생성_표현식(gen, n->데이터.조건문.조건);

    /* 조건이 i1이 아니면 i1으로 변환 */
    if (strcmp(조건.타입, "i1") != 0) {
        int t = 새_임시(gen);
        출력(gen, "    %%%d = icmp ne %s %s, 0\n", t, 조건.타입, 조건.텍스트);
        snprintf(조건.텍스트, LLVM_VAL_LEN, "%%%d", t);
    }

    int 참라벨 = 새_임시(gen);
    int 거짓라벨 = 새_임시(gen);
    int 병합라벨 = 새_임시(gen);

    if (n->데이터.조건문.거짓블록) {
        출력(gen, "    br i1 %s, label %%if.then.%d, label %%if.else.%d\n",
             조건.텍스트, 참라벨, 거짓라벨);
    } else {
        출력(gen, "    br i1 %s, label %%if.then.%d, label %%if.end.%d\n",
             조건.텍스트, 참라벨, 병합라벨);
    }

    /* 참 블록 */
    출력(gen, "if.then.%d:\n", 참라벨);
    if (n->데이터.조건문.참블록 && n->데이터.조건문.참블록->종류 == 노드_블록) {
        for (int i = 0; i < n->데이터.조건문.참블록->데이터.블록.문장_수; i++) {
            생성_문장(gen, n->데이터.조건문.참블록->데이터.블록.문장목록[i]);
        }
    }
    출력(gen, "    br label %%if.end.%d\n", 병합라벨);

    /* 거짓 블록 */
    if (n->데이터.조건문.거짓블록) {
        출력(gen, "if.else.%d:\n", 거짓라벨);
        if (n->데이터.조건문.거짓블록->종류 == 노드_블록) {
            for (int i = 0; i < n->데이터.조건문.거짓블록->데이터.블록.문장_수; i++) {
                생성_문장(gen, n->데이터.조건문.거짓블록->데이터.블록.문장목록[i]);
            }
        }
        출력(gen, "    br label %%if.end.%d\n", 병합라벨);
    }

    출력(gen, "if.end.%d:\n", 병합라벨);
}

/* 동안 반복 */
static void 생성_동안반복(llvm생성기 *gen, 노드 *n) {
    int 조건라벨 = 새_임시(gen);
    int 본문라벨 = 새_임시(gen);
    int 종료라벨 = 새_임시(gen);

    출력(gen, "    br label %%while.cond.%d\n", 조건라벨);
    출력(gen, "while.cond.%d:\n", 조건라벨);

    llvm_값 조건 = 생성_표현식(gen, n->데이터.동안반복.조건);
    if (strcmp(조건.타입, "i1") != 0) {
        int t = 새_임시(gen);
        출력(gen, "    %%%d = icmp ne %s %s, 0\n", t, 조건.타입, 조건.텍스트);
        snprintf(조건.텍스트, LLVM_VAL_LEN, "%%%d", t);
    }
    출력(gen, "    br i1 %s, label %%while.body.%d, label %%while.end.%d\n",
         조건.텍스트, 본문라벨, 종료라벨);

    출력(gen, "while.body.%d:\n", 본문라벨);
    if (n->데이터.동안반복.본문 && n->데이터.동안반복.본문->종류 == 노드_블록) {
        for (int i = 0; i < n->데이터.동안반복.본문->데이터.블록.문장_수; i++) {
            생성_문장(gen, n->데이터.동안반복.본문->데이터.블록.문장목록[i]);
        }
    }
    출력(gen, "    br label %%while.cond.%d\n", 조건라벨);
    출력(gen, "while.end.%d:\n", 종료라벨);
}

/* 범위 반복 */
static void 생성_범위반복(llvm생성기 *gen, 노드 *n) {
    const char *변수이름 = n->데이터.범위반복.변수이름;

    /* 반복 변수 alloca */
    출력(gen, "    %%\"%s\" = alloca i32\n", 변수이름);
    심볼_추가(gen, 변수이름, "i32");

    /* 시작값 저장 */
    llvm_값 시작 = 생성_표현식(gen, n->데이터.범위반복.시작값);
    출력(gen, "    store i32 %s, i32* %%\"%s\"\n", 시작.텍스트, 변수이름);

    int 조건라벨 = 새_임시(gen);
    int 본문라벨 = 새_임시(gen);
    int 종료라벨 = 새_임시(gen);

    출력(gen, "    br label %%for.cond.%d\n", 조건라벨);
    출력(gen, "for.cond.%d:\n", 조건라벨);

    /* 조건: 변수 <= 끝값 */
    int 현재값 = 새_임시(gen);
    출력(gen, "    %%%d = load i32, i32* %%\"%s\"\n", 현재값, 변수이름);
    llvm_값 끝 = 생성_표현식(gen, n->데이터.범위반복.끝값);
    int 비교 = 새_임시(gen);
    출력(gen, "    %%%d = icmp sle i32 %%%d, %s\n", 비교, 현재값, 끝.텍스트);
    출력(gen, "    br i1 %%%d, label %%for.body.%d, label %%for.end.%d\n",
         비교, 본문라벨, 종료라벨);

    /* 본문 */
    출력(gen, "for.body.%d:\n", 본문라벨);
    if (n->데이터.범위반복.본문 && n->데이터.범위반복.본문->종류 == 노드_블록) {
        for (int i = 0; i < n->데이터.범위반복.본문->데이터.블록.문장_수; i++) {
            생성_문장(gen, n->데이터.범위반복.본문->데이터.블록.문장목록[i]);
        }
    }

    /* 증가 */
    int 로드 = 새_임시(gen);
    출력(gen, "    %%%d = load i32, i32* %%\"%s\"\n", 로드, 변수이름);
    int 증가 = 새_임시(gen);
    출력(gen, "    %%%d = add i32 %%%d, 1\n", 증가, 로드);
    출력(gen, "    store i32 %%%d, i32* %%\"%s\"\n", 증가, 변수이름);
    출력(gen, "    br label %%for.cond.%d\n", 조건라벨);

    출력(gen, "for.end.%d:\n", 종료라벨);
}

/* 대입문 */
static void 생성_대입문(llvm생성기 *gen, 노드 *n) {
    llvm_값 값 = 생성_표현식(gen, n->데이터.대입.값);

    if (n->데이터.대입.대상->종류 == 노드_식별자) {
        const char *이름 = n->데이터.대입.대상->데이터.식별자.이름;
        const char *타입 = 심볼_타입_찾기(gen, 이름);
        출력(gen, "    store %s %s, %s* %%\"%s\"\n", 타입, 값.텍스트, 타입, 이름);
    } else if (n->데이터.대입.대상->종류 == 노드_역참조) {
        /* *ptr = value */
        llvm_값 포인터 = 생성_표현식(gen, n->데이터.대입.대상->데이터.참조연산.대상);
        출력(gen, "    store %s %s, %s %s\n", 값.타입, 값.텍스트, 포인터.타입, 포인터.텍스트);
    } else {
        오류(gen, "대입 대상이 올바르지 않습니다");
    }
}

/* 문장 디스패치 */
static void 생성_문장(llvm생성기 *gen, 노드 *n) {
    if (!n || gen->오류_발생) return;

    switch (n->종류) {
    case 노드_변수선언:
        생성_변수선언(gen, n);
        break;
    case 노드_반환문:
        생성_반환문(gen, n);
        break;
    case 노드_조건문:
        생성_조건문(gen, n);
        break;
    case 노드_동안반복:
        생성_동안반복(gen, n);
        break;
    case 노드_범위반복:
        생성_범위반복(gen, n);
        break;
    case 노드_대입:
        생성_대입문(gen, n);
        break;
    case 노드_탈출문:
        /* TODO: break 구현 (가장 가까운 루프의 종료 라벨로 br) */
        break;
    case 노드_계속문:
        /* TODO: continue 구현 */
        break;
    case 노드_블록:
        for (int i = 0; i < n->데이터.블록.문장_수; i++) {
            생성_문장(gen, n->데이터.블록.문장목록[i]);
        }
        break;
    case 노드_표현식문:
        생성_표현식(gen, n->데이터.표현식문.표현식);
        break;
    /* 표현식 노드가 문장 위치에 올 수 있음 */
    case 노드_호출:
        생성_호출(gen, n);
        break;
    default:
        생성_표현식(gen, n);
        break;
    }
}

/* ===== 외부 함수 선언 생성 ===== */

static void 생성_외부선언(llvm생성기 *gen, 노드 *n) {
    const char *이름 = n->데이터.함수정의.이름;
    const char *반환타입 = 타입_변환(n->데이터.함수정의.반환타입);

    출력(gen, "declare %s @%s(", 반환타입, 이름);

    매개변수 *매개 = n->데이터.함수정의.매개변수목록;
    bool 첫번째 = true;
    while (매개) {
        if (!첫번째) 출력(gen, ", ");
        출력(gen, "%s", 타입_변환(매개->타입));
        첫번째 = false;
        매개 = 매개->다음;
    }

    if (n->데이터.함수정의.가변인자) {
        if (!첫번째) 출력(gen, ", ");
        출력(gen, "...");
    }

    출력(gen, ")\n");

    /* 심볼 테이블에 등록 */
    심볼_추가(gen, 이름, 반환타입);
}

/* ===== 나열(enum) 정의 생성 ===== */

static void 생성_나열정의(llvm생성기 *gen, 노드 *n) {
    /* LLVM IR에서 enum은 단순히 정수 상수로 표현 */
    /* 각 값을 심볼 테이블에 등록 */
    for (int i = 0; i < n->데이터.나열정의.값_수; i++) {
        심볼_추가(gen, n->데이터.나열정의.값이름목록[i], "i32");
    }
    /* 실제 LLVM IR에는 아무것도 출력하지 않음 (인라인 상수로 처리) */
}

/* ===== 함수 정의 생성 ===== */

static void 생성_함수정의(llvm생성기 *gen, 노드 *n) {
    const char *이름 = n->데이터.함수정의.이름;
    bool main함수 = (strcmp(이름, "시작하기") == 0);
    const char *반환타입 = main함수 ? "i32" : 타입_변환(n->데이터.함수정의.반환타입);

    /* 함수를 심볼 테이블에 등록 (반환 타입) */
    심볼_추가(gen, 이름, 반환타입);

    /* 지역 심볼 초기화 */
    int 이전_심볼수 = gen->심볼_수;
    gen->임시번호 = 0;

    /* 함수 시그니처 */
    출력(gen, "define %s ", 반환타입);
    if (main함수) {
        출력(gen, "@main");
    } else {
        출력(gen, "@\"%s\"", 이름);
    }
    출력(gen, "(");

    /* 매개변수 */
    매개변수 *매개 = n->데이터.함수정의.매개변수목록;
    bool 첫번째 = true;
    while (매개) {
        if (!첫번째) 출력(gen, ", ");
        const char *매개타입 = 타입_변환(매개->타입);
        출력(gen, "%s %%\"%s.arg\"", 매개타입, 매개->이름);
        첫번째 = false;
        매개 = 매개->다음;
    }
    출력(gen, ") {\nentry:\n");

    /* 매개변수를 alloca로 복사 */
    매개 = n->데이터.함수정의.매개변수목록;
    while (매개) {
        const char *매개타입 = 타입_변환(매개->타입);
        출력(gen, "    %%\"%s\" = alloca %s\n", 매개->이름, 매개타입);
        출력(gen, "    store %s %%\"%s.arg\", %s* %%\"%s\"\n",
             매개타입, 매개->이름, 매개타입, 매개->이름);
        심볼_추가(gen, 매개->이름, 매개타입);
        매개 = 매개->다음;
    }

    /* 본문 */
    if (n->데이터.함수정의.본문 && n->데이터.함수정의.본문->종류 == 노드_블록) {
        노드 *블록 = n->데이터.함수정의.본문;
        for (int i = 0; i < 블록->데이터.블록.문장_수; i++) {
            생성_문장(gen, 블록->데이터.블록.문장목록[i]);
        }
    }

    /* main 함수는 return 0 보장 */
    if (main함수) {
        출력(gen, "    ret i32 0\n");
    }

    출력(gen, "}\n\n");

    /* 지역 심볼 정리 (함수 레벨 심볼은 유지) */
    gen->심볼_수 = 이전_심볼수;
    /* 함수 자체의 심볼은 추가 */
    심볼_추가(gen, 이름, 반환타입);
}

/* ===== 모듈 헤더/전역 출력 ===== */

static void 출력_모듈_헤더(llvm생성기 *gen) {
    출력(gen, "; 글cc LLVM IR 출력\n");
    출력(gen, "; C 의존성 없이 직접 네이티브 코드 생성\n\n");
    출력(gen, "source_filename = \"글_프로그램\"\n");
    출력(gen, "target datalayout = \"e-m:w-p270:32:32-p271:32:32-p272:64:64-i64:64-f80:128-n8:16:32:64-S128\"\n");
    출력(gen, "target triple = \"x86_64-pc-windows-msvc\"\n\n");
}

static void 출력_외부선언(llvm생성기 *gen) {
    출력(gen, "; 외부 함수 선언 (C 런타임)\n");
    if (!외부선언_존재("printf"))
        출력(gen, "declare i32 @printf(i8*, ...)\n");
    if (!외부선언_존재("puts"))
        출력(gen, "declare i32 @puts(i8*)\n");
    if (!외부선언_존재("scanf"))
        출력(gen, "declare i32 @scanf(i8*, ...)\n");
    출력(gen, "\n");
}

static void 출력_포맷_상수(llvm생성기 *gen) {
    출력(gen, "; 출력 포맷 문자열\n");
    출력(gen, "@.fmt.int = private unnamed_addr constant [4 x i8] c\"%%d\\0A\\00\"\n");
    출력(gen, "@.fmt.long = private unnamed_addr constant [6 x i8] c\"%%lld\\0A\\00\"\n");
    출력(gen, "@.fmt.double = private unnamed_addr constant [4 x i8] c\"%%f\\0A\\00\"\n");
    출력(gen, "@.fmt.char = private unnamed_addr constant [4 x i8] c\"%%c\\0A\\00\"\n\n");
}

static void 출력_문자열_상수(llvm생성기 *gen) {
    if (gen->문자열_수 == 0) return;

    출력(gen, "; 문자열 상수\n");
    for (int i = 0; i < gen->문자열_수; i++) {
        llvm_문자열상수 *sc = &gen->문자열[i];
        출력(gen, "@.str.%d = private unnamed_addr constant [%d x i8] ",
             sc->번호, sc->바이트수);
        문자열_바이트_출력(gen, sc->원본);
        출력(gen, "\n");
    }
    출력(gen, "\n");
}

/* ===== 공개 API ===== */

void llvm_생성기_초기화(llvm생성기 *gen, FILE *출력파일) {
    memset(gen, 0, sizeof(llvm생성기));
    gen->출력 = 출력파일;
}

bool llvm_코드_생성(llvm생성기 *gen, 노드 *프로그램) {
    if (!프로그램 || 프로그램->종류 != 노드_프로그램) {
        오류(gen, "프로그램 노드가 필요합니다");
        return false;
    }

    /* === 패스 1: 문자열 상수 수집 + 함수 심볼 등록 === */
    /* (나중에 함수 본문을 생성할 때 자동으로 수집됨) */

    /* === 패스 1.5: 사용자 외부 선언 이름 수집 === */
    사용자_외부선언_수 = 0;
    for (int i = 0; i < 프로그램->데이터.프로그램.선언_수; i++) {
        노드 *선언 = 프로그램->데이터.프로그램.선언목록[i];
        if (선언->종류 == 노드_함수정의 && 선언->데이터.함수정의.외부) {
            if (사용자_외부선언_수 < 128) {
                사용자_외부선언[사용자_외부선언_수++] = 선언->데이터.함수정의.이름;
            }
        }
    }

    /* === 패스 2: 모듈 헤더 출력 === */
    출력_모듈_헤더(gen);
    출력_외부선언(gen);
    출력_포맷_상수(gen);

    /* === 패스 3: 함수 시그니처를 미리 심볼 등록 === */
    for (int i = 0; i < 프로그램->데이터.프로그램.선언_수; i++) {
        노드 *선언 = 프로그램->데이터.프로그램.선언목록[i];
        if (선언->종류 == 노드_함수정의) {
            const char *이름 = 선언->데이터.함수정의.이름;
            if (선언->데이터.함수정의.외부) {
                심볼_추가(gen, 이름, 타입_변환(선언->데이터.함수정의.반환타입));
            } else {
                bool main함수 = (strcmp(이름, "시작하기") == 0);
                const char *반환타입 = main함수 ? "i32" : 타입_변환(선언->데이터.함수정의.반환타입);
                심볼_추가(gen, 이름, 반환타입);
            }
        }
        /* 나열(enum) 값들도 심볼 등록 */
        if (선언->종류 == 노드_나열정의) {
            생성_나열정의(gen, 선언);
        }
    }

    /* === 패스 3.5: 외부 선언 출력 === */
    for (int i = 0; i < 프로그램->데이터.프로그램.선언_수; i++) {
        노드 *선언 = 프로그램->데이터.프로그램.선언목록[i];
        if (선언->종류 == 노드_함수정의 && 선언->데이터.함수정의.외부) {
            생성_외부선언(gen, 선언);
        }
    }
    출력(gen, "\n");

    /* === 패스 4: 함수 본문을 임시 파일에 생성 === */
    FILE *원래출력 = gen->출력;
    FILE *임시파일 = tmpfile();
    if (!임시파일) {
        오류(gen, "임시 파일을 생성할 수 없습니다");
        return false;
    }
    gen->출력 = 임시파일;

    /* 전역 변수 */
    for (int i = 0; i < 프로그램->데이터.프로그램.선언_수; i++) {
        노드 *선언 = 프로그램->데이터.프로그램.선언목록[i];
        if (선언->종류 == 노드_변수선언) {
            const char *이름 = 선언->데이터.변수선언.이름;
            const char *타입 = 타입_변환(선언->데이터.변수선언.타입);
            출력(gen, "@\"%s\" = global %s 0\n", 이름, 타입);
            심볼_추가(gen, 이름, 타입);
        }
    }

    /* 함수 정의 (외부 제외) */
    for (int i = 0; i < 프로그램->데이터.프로그램.선언_수; i++) {
        노드 *선언 = 프로그램->데이터.프로그램.선언목록[i];
        if (선언->종류 == 노드_함수정의 && !선언->데이터.함수정의.외부) {
            생성_함수정의(gen, 선언);
        }
    }

    /* === 패스 5: 문자열 상수를 원래 출력에 쓰기 === */
    gen->출력 = 원래출력;
    출력_문자열_상수(gen);

    /* === 패스 6: 임시 파일 내용을 원래 출력으로 복사 === */
    fseek(임시파일, 0, SEEK_SET);
    char 버퍼[4096];
    size_t 읽은수;
    while ((읽은수 = fread(버퍼, 1, sizeof(버퍼), 임시파일)) > 0) {
        fwrite(버퍼, 1, 읽은수, gen->출력);
    }
    fclose(임시파일);

    /* 정리 */
    for (int i = 0; i < gen->문자열_수; i++) {
        free(gen->문자열[i].원본);
    }
    심볼_해제(gen);

    return !gen->오류_발생;
}
