/*
 * 코드생성기.c - C 코드 생성기 구현
 *
 * 글 언어의 AST를 순회하며 C11 소스 코드를 출력한다.
 * 생성된 코드는 MSVC /utf-8 또는 GCC/Clang에서 컴파일 가능하다.
 */

#include "코드생성기.h"
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>

/* ===== 내부 전방 선언 ===== */

static void 생성_노드(코드생성기 *gen, 노드 *n);
static void 생성_선언(코드생성기 *gen, 노드 *n);
static void 생성_문장(코드생성기 *gen, 노드 *n);
static void 생성_표현식(코드생성기 *gen, 노드 *n);
static void 생성_타입(코드생성기 *gen, 노드 *타입);
static void 생성_블록(코드생성기 *gen, 노드 *n);
static void 생성_함수정의(코드생성기 *gen, 노드 *n);
static void 생성_함수_전방선언(코드생성기 *gen, 노드 *n);
static void 생성_변수선언(코드생성기 *gen, 노드 *n);
static void 생성_묶음정의(코드생성기 *gen, 노드 *n);
static void 생성_나열정의(코드생성기 *gen, 노드 *n);
static void 생성_조건문(코드생성기 *gen, 노드 *n);
static void 생성_동안반복(코드생성기 *gen, 노드 *n);
static void 생성_반복하기(코드생성기 *gen, 노드 *n);
static void 생성_범위반복(코드생성기 *gen, 노드 *n);
static void 생성_반복문(코드생성기 *gen, 노드 *n);
static void 생성_반환문(코드생성기 *gen, 노드 *n);
static void 생성_대입(코드생성기 *gen, 노드 *n);
static void 생성_호출(코드생성기 *gen, 노드 *n);
static void 생성_이항연산(코드생성기 *gen, 노드 *n);
static void 생성_단항연산(코드생성기 *gen, 노드 *n);
static void 생성_멤버접근(코드생성기 *gen, 노드 *n);
static void 생성_배열접근(코드생성기 *gen, 노드 *n);
static void 생성_형변환(코드생성기 *gen, 노드 *n);
static void 생성_파이프라인(코드생성기 *gen, 노드 *n);
static void 생성_크기연산(코드생성기 *gen, 노드 *n);
static void 생성_전처리(코드생성기 *gen, 노드 *n);

static void 출력_런타임(코드생성기 *gen);
static void 출력_헤더(코드생성기 *gen);
static bool 나열이름인가(코드생성기 *gen, const char *이름);
static void 나열이름_등록(코드생성기 *gen, const char *이름);
static bool 별칭이름인가(코드생성기 *gen, const char *이름);
static void 별칭이름_등록(코드생성기 *gen, const char *이름);
static bool 합침이름인가(코드생성기 *gen, const char *이름);
static void 합침이름_등록(코드생성기 *gen, const char *이름);

/* ===== 유틸리티 함수 ===== */

static void 오류_설정(코드생성기 *gen, const char *형식, ...) {
    va_list ap;
    va_start(ap, 형식);
    vsnprintf(gen->오류_메시지, sizeof(gen->오류_메시지), 형식, ap);
    va_end(ap);
    gen->오류_발생 = true;
}

static void 출력(코드생성기 *gen, const char *형식, ...) {
    va_list ap;
    va_start(ap, 형식);
    vfprintf(gen->출력, 형식, ap);
    va_end(ap);
}

static void 들여쓰기(코드생성기 *gen) {
    for (int i = 0; i < gen->들여쓰기_깊이; i++) {
        fprintf(gen->출력, "    ");
    }
}

static void 줄출력(코드생성기 *gen, const char *형식, ...) {
    들여쓰기(gen);
    va_list ap;
    va_start(ap, 형식);
    vfprintf(gen->출력, 형식, ap);
    va_end(ap);
    fprintf(gen->출력, "\n");
}

/* 함수 이름 변환: 시작하기 → main */
static const char *함수이름_변환(const char *이름) {
    if (strcmp(이름, "시작하기") == 0) {
        return "main";
    }
    return 이름;
}

/* 연산자 토큰을 C 연산자 문자열로 변환 */
static const char *연산자_문자열(토큰_종류 연산자) {
    switch (연산자) {
        case 토큰_더하기:       return "+";
        case 토큰_빼기:         return "-";
        case 토큰_곱하기:       return "*";
        case 토큰_나누기:       return "/";
        case 토큰_나머지:       return "%";
        case 토큰_같다:         return "==";
        case 토큰_다르다:       return "!=";
        case 토큰_크다:         return ">";
        case 토큰_작다:         return "<";
        case 토큰_크거나같다:   return ">=";
        case 토큰_작거나같다:   return "<=";
        case 토큰_그리고:       return "&&";
        case 토큰_또는:         return "||";
        case 토큰_아닌:         return "!";
        case 토큰_비트와:       return "&";
        case 토큰_비트또는:     return "|";
        case 토큰_비트배타:     return "^";
        case 토큰_비트아닌:     return "~";
        case 토큰_왼쪽이동:     return "<<";
        case 토큰_오른쪽이동:   return ">>";
        case 토큰_대입:         return "=";
        default:                return "/* 알 수 없는 연산자 */";
    }
}

/* ===== 초기화 ===== */

void 생성기_초기화(코드생성기 *gen, FILE *출력파일) {
    gen->출력 = 출력파일;
    gen->들여쓰기_깊이 = 0;
    gen->임시변수_번호 = 0;
    gen->오류_발생 = false;
    gen->오류_메시지[0] = '\0';
    gen->나열이름_수 = 0;
    gen->별칭이름_수 = 0;
    gen->합침이름_수 = 0;
}

/* ===== 타입 생성 ===== */

static void 생성_타입(코드생성기 *gen, 노드 *타입) {
    if (!타입) {
        출력(gen, "void");
        return;
    }

    switch (타입->종류) {
        case 노드_기본타입:
            switch (타입->데이터.기본타입.기본) {
                case 토큰_정수:       출력(gen, "int");             break;
                case 토큰_긴정수:     출력(gen, "long long");       break;
                case 토큰_짧은정수:   출력(gen, "short");           break;
                case 토큰_작은정수:   출력(gen, "char");            break;
                case 토큰_부호없는:   출력(gen, "unsigned int");    break;
                case 토큰_실수:       출력(gen, "double");          break;
                case 토큰_짧은실수:   출력(gen, "float");           break;
                case 토큰_문자:       출력(gen, "char");            break;
                case 토큰_문자열:     출력(gen, "char*");            break;
                case 토큰_참거짓:     출력(gen, "int");             break;
                case 토큰_공허:       출력(gen, "void");            break;
                case 토큰_가변목록:  출력(gen, "va_list");         break;
                default:
                    오류_설정(gen, "알 수 없는 기본 타입: %d", 타입->데이터.기본타입.기본);
                    출력(gen, "/* 알 수 없는 타입 */int");
                    break;
            }
            break;

        case 노드_참조타입:
            생성_타입(gen, 타입->데이터.참조타입.대상타입);
            출력(gen, "*");
            break;

        case 노드_배열타입:
            /* 배열 타입은 선언 시 특별 처리 필요 */
            생성_타입(gen, 타입->데이터.배열타입.원소타입);
            break;

        case 노드_묶음타입명:
            if (별칭이름인가(gen, 타입->데이터.묶음타입명.이름))
                출력(gen, "%s", 타입->데이터.묶음타입명.이름);
            else if (나열이름인가(gen, 타입->데이터.묶음타입명.이름))
                출력(gen, "enum %s", 타입->데이터.묶음타입명.이름);
            else if (합침이름인가(gen, 타입->데이터.묶음타입명.이름))
                출력(gen, "union %s", 타입->데이터.묶음타입명.이름);
            else
                출력(gen, "struct %s", 타입->데이터.묶음타입명.이름);
            break;

        case 노드_함수포인터타입:
            /* 이름 없는 함수 포인터 타입: 반환타입 (*)(매개변수들) */
            생성_타입(gen, 타입->데이터.함수포인터타입.반환타입);
            출력(gen, " (*)(");
            for (int i = 0; i < 타입->데이터.함수포인터타입.매개변수타입_수; i++) {
                if (i > 0) 출력(gen, ", ");
                생성_타입(gen, 타입->데이터.함수포인터타입.매개변수타입들[i]);
            }
            출력(gen, ")");
            break;

        default:
            오류_설정(gen, "타입 노드가 아닌 노드를 타입으로 사용: %d", 타입->종류);
            출력(gen, "/* 타입 오류 */int");
            break;
    }
}

/* 함수 포인터 타입으로 이름 있는 선언 생성: 반환타입 (*이름)(매개변수타입들) */
static void 생성_함수포인터_선언(코드생성기 *gen, 노드 *타입, const char *이름) {
    생성_타입(gen, 타입->데이터.함수포인터타입.반환타입);
    출력(gen, " (*%s)(", 이름);
    for (int i = 0; i < 타입->데이터.함수포인터타입.매개변수타입_수; i++) {
        if (i > 0) 출력(gen, ", ");
        생성_타입(gen, 타입->데이터.함수포인터타입.매개변수타입들[i]);
    }
    출력(gen, ")");
}

/* 배열 크기 접미사 생성 (변수 이름 뒤에 [N] 출력) */
static void 생성_배열_접미사(코드생성기 *gen, 노드 *타입) {
    if (타입 && 타입->종류 == 노드_배열타입) {
        출력(gen, "[%d]", 타입->데이터.배열타입.크기);
    }
}

/* ===== 헤더 및 런타임 출력 ===== */

static void 출력_헤더(코드생성기 *gen) {
    출력(gen, "/* 글cc에 의해 생성됨 */\n");
    출력(gen, "#include <stdio.h>\n");
    출력(gen, "#include <stdlib.h>\n");
    출력(gen, "#include <string.h>\n");
    출력(gen, "#include <stdarg.h>\n");
    출력(gen, "#include <locale.h>\n");
    출력(gen, "#ifdef _WIN32\n");
    출력(gen, "#include <windows.h>\n");
    출력(gen, "#endif\n");
    출력(gen, "\n");
}

static void 출력_런타임(코드생성기 *gen) {
    출력(gen, "/* ===== 글 런타임 함수 ===== */\n\n");

    출력(gen, "#ifdef _WIN32\n");
    출력(gen, "static char* _ansi_to_utf8(const char* s) {\n");
    출력(gen, "    int wl = MultiByteToWideChar(0, 0, s, -1, NULL, 0);\n");
    출력(gen, "    wchar_t* ws = (wchar_t*)malloc(wl * sizeof(wchar_t));\n");
    출력(gen, "    MultiByteToWideChar(0, 0, s, -1, ws, wl);\n");
    출력(gen, "    int ul = WideCharToMultiByte(65001, 0, ws, -1, NULL, 0, NULL, NULL);\n");
    출력(gen, "    char* u = (char*)malloc(ul);\n");
    출력(gen, "    WideCharToMultiByte(65001, 0, ws, -1, u, ul, NULL, NULL);\n");
    출력(gen, "    free(ws); return u;\n");
    출력(gen, "}\n");
    출력(gen, "#endif\n\n");

    /* 출력 함수들 */
    출력(gen, "static void 출력_정수(int v) { printf(\"%%d\\n\", v); }\n");
    출력(gen, "static void 출력_긴정수(long long v) { printf(\"%%lld\\n\", v); }\n");
    출력(gen, "static void 출력_실수(double v) { printf(\"%%f\\n\", v); }\n");
    출력(gen, "static void 출력_문자열(char *v) { printf(\"%%s\\n\", v); }\n");
    출력(gen, "static void 출력_문자(char v) { printf(\"%%c\\n\", v); }\n");
    출력(gen, "\n");
    /* 문자열 리터럴 "abc"의 타입은 char[N]이므로 _Generic에서 직접 매칭 불가.
     * (0, (x))를 사용하면 배열이 포인터로 decay됨 (comma operator). */
    출력(gen, "#define 출력(x) _Generic((0, (x)), \\\n");
    출력(gen, "    int: 출력_정수, \\\n");
    출력(gen, "    long long: 출력_긴정수, \\\n");
    출력(gen, "    double: 출력_실수, \\\n");
    출력(gen, "    float: 출력_실수, \\\n");
    출력(gen, "    char: 출력_문자, \\\n");
    출력(gen, "    char*: 출력_문자열 \\\n");
    출력(gen, ")(x)\n");
    출력(gen, "\n");

    /* 보간 출력 매크로 — 문자열 보간용 */
    출력(gen, "static void _보간_int(int v) { printf(\"%%d\", v); }\n");
    출력(gen, "static void _보간_lld(long long v) { printf(\"%%lld\", v); }\n");
    출력(gen, "static void _보간_dbl(double v) { printf(\"%%g\", v); }\n");
    출력(gen, "static void _보간_str(char *v) { printf(\"%%s\", v); }\n");
    출력(gen, "static void _보간_chr(char v) { printf(\"%%c\", v); }\n");
    출력(gen, "#define _보간(x) _Generic((0,(x)), \\\n");
    출력(gen, "    int: _보간_int, long long: _보간_lld, \\\n");
    출력(gen, "    double: _보간_dbl, float: _보간_dbl, \\\n");
    출력(gen, "    char: _보간_chr, char*: _보간_str)(x)\n\n");

    /* 입력 함수 스텁 */
    출력(gen, "/* 입력 함수 스텁 */\n");
    출력(gen, "static int 입력_정수(void) {\n");
    출력(gen, "    int v;\n");
    출력(gen, "    scanf(\"%%d\", &v);\n");
    출력(gen, "    return v;\n");
    출력(gen, "}\n");
    출력(gen, "\n");
    출력(gen, "static double 입력_실수(void) {\n");
    출력(gen, "    double v;\n");
    출력(gen, "    scanf(\"%%lf\", &v);\n");
    출력(gen, "    return v;\n");
    출력(gen, "}\n");
    출력(gen, "\n");
    출력(gen, "static void 입력_문자열(char *buf, int 크기) {\n");
    출력(gen, "    fgets(buf, 크기, stdin);\n");
    출력(gen, "    buf[strcspn(buf, \"\\n\")] = '\\0';\n");
    출력(gen, "}\n");
    출력(gen, "\n");
}

/* ===== 전방 선언 생성 ===== */

/* C 표준 라이브러리에 이미 선언된 함수인지 확인 */
static bool C_표준_함수인가(const char *이름) {
    static const char *표준[] = {
        "strlen", "strcmp", "strcpy", "strcat", "strstr", "strncpy",
        "strncmp", "strncat", "strchr", "strrchr", "memcpy", "memset",
        "memmove", "memcmp", "malloc", "calloc", "realloc", "free",
        "printf", "fprintf", "sprintf", "snprintf", "puts", "fputs",
        "fopen", "fclose", "fread", "fwrite", "fseek", "ftell",
        "fgets", "fputc", "fgetc", "scanf", "sscanf",
        "atoi", "atol", "atof", "abs", "exit", "system",
        NULL
    };
    for (int i = 0; 표준[i]; i++) {
        if (strcmp(이름, 표준[i]) == 0) return true;
    }
    return false;
}

static void 생성_함수_전방선언(코드생성기 *gen, 노드 *n) {
    if (n->종류 != 노드_함수정의) return;

    const char *이름 = 함수이름_변환(n->데이터.함수정의.이름);

    /* 외부(extern) 선언: C 표준 함수는 이미 헤더에 선언되어 있으므로 건너뜀 */
    if (n->데이터.함수정의.외부) {
        if (C_표준_함수인가(이름)) return;
        출력(gen, "extern ");
    } else if (n->데이터.함수정의.정적) {
        출력(gen, "static ");
    }

    /* 반환 타입: main은 항상 int */
    if (strcmp(이름, "main") == 0) {
        출력(gen, "int");
    } else {
        생성_타입(gen, n->데이터.함수정의.반환타입);
    }
    출력(gen, " %s(", 이름);

    /* 매개변수 목록 */
    매개변수 *매개 = n->데이터.함수정의.매개변수목록;
    if (!매개 && !n->데이터.함수정의.가변인자) {
        출력(gen, "void");
    } else {
        bool 첫번째 = true;
        while (매개) {
            if (!첫번째) 출력(gen, ", ");
            if (매개->상수) 출력(gen, "const ");
            if (매개->타입 && 매개->타입->종류 == 노드_함수포인터타입) {
                생성_함수포인터_선언(gen, 매개->타입, 매개->이름);
            } else {
                생성_타입(gen, 매개->타입);
                출력(gen, " %s", 매개->이름);
                생성_배열_접미사(gen, 매개->타입);
            }
            첫번째 = false;
            매개 = 매개->다음;
        }
        if (n->데이터.함수정의.가변인자) {
            if (!첫번째) 출력(gen, ", ");
            출력(gen, "...");
        }
    }

    출력(gen, ");\n");
}

/* ===== 함수 정의 생성 ===== */

static void 생성_함수정의(코드생성기 *gen, 노드 *n) {
    /* 외부(extern) 선언은 전방선언으로만 생성, 본문 없음 */
    if (n->데이터.함수정의.외부) return;

    const char *이름 = 함수이름_변환(n->데이터.함수정의.이름);
    bool main함수 = (strcmp(이름, "main") == 0);

    /* static 접두사 */
    if (n->데이터.함수정의.정적) 출력(gen, "static ");

    /* 반환 타입: main은 항상 int */
    if (main함수) {
        출력(gen, "int");
    } else {
        생성_타입(gen, n->데이터.함수정의.반환타입);
    }
    출력(gen, " %s(", 이름);

    /* 매개변수 목록 */
    매개변수 *매개 = n->데이터.함수정의.매개변수목록;
    if (!매개 && !n->데이터.함수정의.가변인자) {
        출력(gen, "void");
    } else {
        bool 첫번째 = true;
        while (매개) {
            if (!첫번째) 출력(gen, ", ");
            if (매개->상수) 출력(gen, "const ");
            if (매개->타입 && 매개->타입->종류 == 노드_함수포인터타입) {
                생성_함수포인터_선언(gen, 매개->타입, 매개->이름);
            } else {
                생성_타입(gen, 매개->타입);
                출력(gen, " %s", 매개->이름);
                생성_배열_접미사(gen, 매개->타입);
            }
            첫번째 = false;
            매개 = 매개->다음;
        }
        if (n->데이터.함수정의.가변인자) {
            if (!첫번째) 출력(gen, ", ");
            출력(gen, "...");
        }
    }

    출력(gen, ") ");

    /* main 함수: 본문 마지막에 return 0 추가 */
    if (main함수) {
        노드 *본문 = n->데이터.함수정의.본문;
        if (본문 && 본문->종류 == 노드_블록) {
            출력(gen, "{\n");
            gen->들여쓰기_깊이++;
            줄출력(gen, "setlocale(LC_ALL, \".UTF-8\");");
            if (n->데이터.함수정의.매개변수목록) {
                출력(gen, "#ifdef _WIN32\n");
                줄출력(gen, "for(int _i=0;_i<argc;_i++){argv[_i]=_ansi_to_utf8(argv[_i]);}");
                출력(gen, "#endif\n");
            }
            for (int i = 0; i < 본문->데이터.블록.문장_수; i++) {
                생성_문장(gen, 본문->데이터.블록.문장목록[i]);
            }
            줄출력(gen, "return 0;");
            gen->들여쓰기_깊이--;
            들여쓰기(gen);
            출력(gen, "}");
        } else {
            생성_블록(gen, 본문);
        }
    } else {
        생성_블록(gen, n->데이터.함수정의.본문);
    }
    출력(gen, "\n\n");
}

/* ===== 블록 생성 ===== */

static void 생성_블록(코드생성기 *gen, 노드 *n) {
    if (!n || n->종류 != 노드_블록) {
        출력(gen, "{ }\n");
        return;
    }

    출력(gen, "{\n");
    gen->들여쓰기_깊이++;

    for (int i = 0; i < n->데이터.블록.문장_수; i++) {
        생성_문장(gen, n->데이터.블록.문장목록[i]);
    }

    gen->들여쓰기_깊이--;
    들여쓰기(gen);
    출력(gen, "}");
}

/* ===== 변수 선언 생성 ===== */

static void 생성_변수선언(코드생성기 *gen, 노드 *n) {
    들여쓰기(gen);
    if (n->데이터.변수선언.외부) 출력(gen, "extern ");
    if (n->데이터.변수선언.정적) 출력(gen, "static ");
    if (n->데이터.변수선언.상수) 출력(gen, "const ");

    /* 함수 포인터 타입은 이름이 타입 중간에 삽입됨 */
    if (n->데이터.변수선언.타입 &&
        n->데이터.변수선언.타입->종류 == 노드_함수포인터타입) {
        생성_함수포인터_선언(gen, n->데이터.변수선언.타입,
                             n->데이터.변수선언.이름);
    } else {
        생성_타입(gen, n->데이터.변수선언.타입);
        출력(gen, " %s", n->데이터.변수선언.이름);
        생성_배열_접미사(gen, n->데이터.변수선언.타입);
    }

    if (n->데이터.변수선언.초기값) {
        출력(gen, " = ");
        생성_표현식(gen, n->데이터.변수선언.초기값);
    }

    출력(gen, ";\n");
}

/* ===== 묶음(struct) 정의 생성 ===== */

static void 생성_묶음정의(코드생성기 *gen, 노드 *n) {
    출력(gen, "struct %s {\n", n->데이터.묶음정의.이름);
    gen->들여쓰기_깊이++;

    묶음필드 *필드 = n->데이터.묶음정의.필드목록;
    while (필드) {
        들여쓰기(gen);
        if (필드->타입 && 필드->타입->종류 == 노드_함수포인터타입) {
            생성_함수포인터_선언(gen, 필드->타입, 필드->이름);
        } else {
            생성_타입(gen, 필드->타입);
            출력(gen, " %s", 필드->이름);
            생성_배열_접미사(gen, 필드->타입);
        }
        출력(gen, ";\n");
        필드 = 필드->다음;
    }

    gen->들여쓰기_깊이--;
    출력(gen, "};\n\n");
}

/* ===== 합침(union) 이름 관리 ===== */

static bool 합침이름인가(코드생성기 *gen, const char *이름) {
    for (int i = 0; i < gen->합침이름_수; i++) {
        if (strcmp(gen->합침이름목록[i], 이름) == 0) return true;
    }
    return false;
}

static void 합침이름_등록(코드생성기 *gen, const char *이름) {
    if (gen->합침이름_수 < 128 && !합침이름인가(gen, 이름)) {
        gen->합침이름목록[gen->합침이름_수++] = strdup(이름);
    }
}

/* ===== 합침(union) 정의 생성 ===== */

static void 생성_합침정의(코드생성기 *gen, 노드 *n) {
    합침이름_등록(gen, n->데이터.합침정의.이름);
    출력(gen, "union %s {\n", n->데이터.합침정의.이름);
    gen->들여쓰기_깊이++;

    묶음필드 *필드 = n->데이터.합침정의.필드목록;
    while (필드) {
        들여쓰기(gen);
        if (필드->타입 && 필드->타입->종류 == 노드_함수포인터타입) {
            생성_함수포인터_선언(gen, 필드->타입, 필드->이름);
        } else {
            생성_타입(gen, 필드->타입);
            출력(gen, " %s", 필드->이름);
            생성_배열_접미사(gen, 필드->타입);
        }
        출력(gen, ";\n");
        필드 = 필드->다음;
    }

    gen->들여쓰기_깊이--;
    출력(gen, "};\n\n");
}

/* ===== 나열(enum) 정의 생성 ===== */

static bool 나열이름인가(코드생성기 *gen, const char *이름) {
    for (int i = 0; i < gen->나열이름_수; i++) {
        if (strcmp(gen->나열이름목록[i], 이름) == 0) return true;
    }
    return false;
}

static void 나열이름_등록(코드생성기 *gen, const char *이름) {
    if (gen->나열이름_수 < 128 && !나열이름인가(gen, 이름)) {
        gen->나열이름목록[gen->나열이름_수++] = strdup(이름);
    }
}

/* ===== 별칭(typedef) 이름 관리 ===== */

static bool 별칭이름인가(코드생성기 *gen, const char *이름) {
    for (int i = 0; i < gen->별칭이름_수; i++) {
        if (strcmp(gen->별칭이름목록[i], 이름) == 0) return true;
    }
    return false;
}

static void 별칭이름_등록(코드생성기 *gen, const char *이름) {
    if (gen->별칭이름_수 < 128 && !별칭이름인가(gen, 이름)) {
        gen->별칭이름목록[gen->별칭이름_수++] = strdup(이름);
    }
}

static void 생성_나열정의(코드생성기 *gen, 노드 *n) {
    나열이름_등록(gen, n->데이터.나열정의.이름);
    출력(gen, "enum %s {\n", n->데이터.나열정의.이름);
    gen->들여쓰기_깊이++;

    for (int i = 0; i < n->데이터.나열정의.값_수; i++) {
        들여쓰기(gen);
        출력(gen, "%s", n->데이터.나열정의.값이름목록[i]);
        if (n->데이터.나열정의.값목록) {
            출력(gen, " = %d", n->데이터.나열정의.값목록[i]);
        }
        if (i < n->데이터.나열정의.값_수 - 1) {
            출력(gen, ",");
        }
        출력(gen, "\n");
    }

    gen->들여쓰기_깊이--;
    출력(gen, "};\n\n");
}

/* ===== 조건문 생성 ===== */

static void 생성_조건문(코드생성기 *gen, 노드 *n) {
    들여쓰기(gen);
    출력(gen, "if (");
    생성_표현식(gen, n->데이터.조건문.조건);
    출력(gen, ") ");
    생성_블록(gen, n->데이터.조건문.참블록);

    if (n->데이터.조건문.거짓블록) {
        출력(gen, " else ");
        if (n->데이터.조건문.거짓블록->종류 == 노드_조건문) {
            /* else if 체인 */
            출력(gen, "\n");
            생성_조건문(gen, n->데이터.조건문.거짓블록);
            return;
        } else {
            생성_블록(gen, n->데이터.조건문.거짓블록);
        }
    }
    출력(gen, "\n");
}

/* ===== 동안 반복 생성 ===== */

static void 생성_동안반복(코드생성기 *gen, 노드 *n) {
    들여쓰기(gen);
    출력(gen, "while (");
    생성_표현식(gen, n->데이터.동안반복.조건);
    출력(gen, ") ");
    생성_블록(gen, n->데이터.동안반복.본문);
    출력(gen, "\n");
}

/* ===== 반복하기 (do-while) 생성 ===== */

static void 생성_반복하기(코드생성기 *gen, 노드 *n) {
    들여쓰기(gen);
    출력(gen, "do ");
    생성_블록(gen, n->데이터.반복하기.본문);
    출력(gen, " while (");
    생성_표현식(gen, n->데이터.반복하기.조건);
    출력(gen, ");\n");
}

/* ===== 범위 반복 생성 ===== */

static void 생성_범위반복(코드생성기 *gen, 노드 *n) {
    들여쓰기(gen);
    출력(gen, "for (int %s = ", n->데이터.범위반복.변수이름);
    생성_표현식(gen, n->데이터.범위반복.시작값);
    출력(gen, "; %s <= ", n->데이터.범위반복.변수이름);
    생성_표현식(gen, n->데이터.범위반복.끝값);
    출력(gen, "; %s++) ", n->데이터.범위반복.변수이름);
    생성_블록(gen, n->데이터.범위반복.본문);
    출력(gen, "\n");
}

/* ===== 반복문 (C-style for) 생성 ===== */

static void 생성_반복문(코드생성기 *gen, 노드 *n) {
    들여쓰기(gen);
    출력(gen, "for (");

    /* 초기화 */
    if (n->데이터.반복문.초기화) {
        if (n->데이터.반복문.초기화->종류 == 노드_변수선언) {
            생성_타입(gen, n->데이터.반복문.초기화->데이터.변수선언.타입);
            출력(gen, " %s", n->데이터.반복문.초기화->데이터.변수선언.이름);
            if (n->데이터.반복문.초기화->데이터.변수선언.초기값) {
                출력(gen, " = ");
                생성_표현식(gen, n->데이터.반복문.초기화->데이터.변수선언.초기값);
            }
        } else {
            생성_표현식(gen, n->데이터.반복문.초기화);
        }
    }
    출력(gen, "; ");

    /* 조건 */
    if (n->데이터.반복문.조건) {
        생성_표현식(gen, n->데이터.반복문.조건);
    }
    출력(gen, "; ");

    /* 증감 */
    if (n->데이터.반복문.증감) {
        생성_표현식(gen, n->데이터.반복문.증감);
    }
    출력(gen, ") ");

    생성_블록(gen, n->데이터.반복문.본문);
    출력(gen, "\n");
}

/* ===== 반환문 생성 ===== */

static void 생성_반환문(코드생성기 *gen, 노드 *n) {
    들여쓰기(gen);
    if (n->데이터.반환문.값) {
        출력(gen, "return ");
        생성_표현식(gen, n->데이터.반환문.값);
        출력(gen, ";\n");
    } else {
        출력(gen, "return;\n");
    }
}

/* ===== 대입 생성 ===== */

static void 생성_대입(코드생성기 *gen, 노드 *n) {
    생성_표현식(gen, n->데이터.대입.대상);
    switch (n->데이터.대입.연산자) {
    case 토큰_더하기대입: 출력(gen, " += "); break;
    case 토큰_빼기대입:   출력(gen, " -= "); break;
    case 토큰_곱하기대입: 출력(gen, " *= "); break;
    case 토큰_나누기대입: 출력(gen, " /= "); break;
    case 토큰_나머지대입: 출력(gen, " %%= "); break;
    default:              출력(gen, " = "); break;
    }
    생성_표현식(gen, n->데이터.대입.값);
}

/* ===== 비교 동사 → C 연산자 변환 ===== */

static const char *비교동사_연산자(const char *이름) {
    /* 작다 (less than) - 어간 변형들 */
    if (strcmp(이름, "작은") == 0 || strcmp(이름, "작으") == 0) return "<";
    /* 크다 (greater than) */
    if (strcmp(이름, "큰") == 0 || strcmp(이름, "크") == 0) return ">";
    /* 작거나같다 (less than or equal) */
    if (strcmp(이름, "작거나같은") == 0 || strcmp(이름, "작거나같으") == 0) return "<=";
    /* 크거나같다 (greater than or equal) */
    if (strcmp(이름, "크거나같은") == 0 || strcmp(이름, "크거나같으") == 0) return ">=";
    /* 같다 (equal) */
    if (strcmp(이름, "같은") == 0 || strcmp(이름, "같으") == 0) return "==";
    /* 다르다 (not equal) */
    if (strcmp(이름, "다른") == 0 || strcmp(이름, "다르") == 0) return "!=";
    return NULL;
}

/* ===== 함수 호출 생성 ===== */

static void 생성_호출(코드생성기 *gen, 노드 *n) {
    const char *이름 = n->데이터.호출.함수이름;

    /* 비교 동사 → C 비교 연산자로 변환 */
    const char *비교연산 = 비교동사_연산자(이름);
    if (비교연산) {
        /* 주어(이/가)와 비교대상(보다)을 찾아 연산자로 연결 */
        인자 *주어 = NULL;
        인자 *비교대상 = NULL;
        인자 *인자p = n->데이터.호출.인자목록;
        while (인자p) {
            if (인자p->역할 == 역할_주어) 주어 = 인자p;
            else if (인자p->역할 == 역할_비교) 비교대상 = 인자p;
            else if (!주어) 주어 = 인자p;
            else if (!비교대상) 비교대상 = 인자p;
            인자p = 인자p->다음;
        }
        if (주어 && 비교대상) {
            출력(gen, "(");
            생성_표현식(gen, 주어->값);
            출력(gen, " %s ", 비교연산);
            생성_표현식(gen, 비교대상->값);
            출력(gen, ")");
            return;
        }
        /* 인자 역할이 불분명한 경우: 첫째=왼쪽, 둘째=오른쪽 */
        인자p = n->데이터.호출.인자목록;
        if (인자p && 인자p->다음) {
            출력(gen, "(");
            생성_표현식(gen, 인자p->값);
            출력(gen, " %s ", 비교연산);
            생성_표현식(gen, 인자p->다음->값);
            출력(gen, ")");
            return;
        }
    }

    /*
     * 문자열 보간 처리:
     * "이름은 {이름}이고 {나이}세\n"을 쓰다.
     * → printf("이름은 "); _보간(이름); printf("이고 "); _보간(나이); printf("세\n");
     */
    인자 *첫인자 = n->데이터.호출.인자목록;
    if (첫인자 && 첫인자->값 && 첫인자->값->종류 == 노드_문자열_리터럴) {
        const char *s = 첫인자->값->데이터.문자열_리터럴.값;
        /* 보간 문자열 감지: {순수식별자} 패턴만 보간 */
        /* {와} 사이에 알파벳/한글/밑줄/숫자만 있어야 함 — [, =, ; 등 포함시 무시 */
        bool 보간있음 = false;
        for (const char *p = s; *p; p++) {
            if (*p == '{' && (p == s || *(p-1) != '\\')) {
                const char *q = p + 1;
                /* 첫 글자: 알파벳/한글/밑줄 */
                unsigned char 첫 = (unsigned char)*q;
                if (!((첫 >= 'A' && 첫 <= 'Z') || (첫 >= 'a' && 첫 <= 'z') ||
                      첫 == '_' || 첫 >= 0x80)) continue;
                /* 나머지: 알파벳/한글/밑줄/숫자만, }까지 */
                while (*q && *q != '}') {
                    unsigned char c = (unsigned char)*q;
                    if (!((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') ||
                          (c >= '0' && c <= '9') || c == '_' || c >= 0x80)) break;
                    q++;
                }
                if (*q == '}' && q > p + 1) { 보간있음 = true; break; }
            }
        }
        if (보간있음) {
            /* 보간 문자열을 printf + _보간 체인으로 변환 */
            출력(gen, "do { ");
            const char *p = s;
            while (*p) {
                /* {순수식별자} 패턴인지 확인 */
                bool _보간시작 = false;
                if (*p == '{' && (p == s || *(p-1) != '\\')) {
                    const char *_q = p + 1;
                    unsigned char _fc = (unsigned char)*_q;
                    if ((_fc >= 'A' && _fc <= 'Z') || (_fc >= 'a' && _fc <= 'z') ||
                        _fc == '_' || _fc >= 0x80) {
                        while (*_q && *_q != '}') {
                            unsigned char _cc = (unsigned char)*_q;
                            if (!((_cc >= 'A' && _cc <= 'Z') || (_cc >= 'a' && _cc <= 'z') ||
                                  (_cc >= '0' && _cc <= '9') || _cc == '_' || _cc >= 0x80)) break;
                            _q++;
                        }
                        if (*_q == '}' && _q > p + 1) _보간시작 = true;
                    }
                }
                if (_보간시작) {
                    p++; /* '{' 건너뛰기 */
                    /* 변수이름 추출 */
                    const char *이름시작 = p;
                    while (*p && *p != '}') p++;
                    int 이름길이 = (int)(p - 이름시작);
                    if (*p == '}') p++;
                    출력(gen, "_보간(");
                    fwrite(이름시작, 1, 이름길이, gen->출력);
                    출력(gen, "); ");
                } else {
                    /* 일반 텍스트 구간: 다음 보간{순수식별자} 또는 끝까지 수집 */
                    const char *텍스트시작 = p;
                    while (*p) {
                        if (*p == '{' && (p == 텍스트시작 || *(p-1) != '\\')) {
                            const char *_tq = p + 1;
                            unsigned char _tfc = (unsigned char)*_tq;
                            if ((_tfc >= 'A' && _tfc <= 'Z') || (_tfc >= 'a' && _tfc <= 'z') ||
                                _tfc == '_' || _tfc >= 0x80) {
                                while (*_tq && *_tq != '}') {
                                    unsigned char _tc = (unsigned char)*_tq;
                                    if (!((_tc >= 'A' && _tc <= 'Z') || (_tc >= 'a' && _tc <= 'z') ||
                                          (_tc >= '0' && _tc <= '9') || _tc == '_' || _tc >= 0x80)) break;
                                    _tq++;
                                }
                                if (*_tq == '}' && _tq > p + 1) break;
                            }
                        }
                        p++;
                    }
                    출력(gen, "printf(\"");
                    for (const char *t = 텍스트시작; t < p; t++) {
                        switch (*t) {
                        case '\n': 출력(gen, "\\n"); break;
                        case '\t': 출력(gen, "\\t"); break;
                        case '\\': 출력(gen, "\\\\"); break;
                        case '"':  출력(gen, "\\\""); break;
                        case '%':  출력(gen, "%%%%"); break;
                        default: fprintf(gen->출력, "%c", *t); break;
                        }
                    }
                    출력(gen, "\"); ");
                }
            }
            출력(gen, "} while(0)");
            return;
        }
    }

    /*
     * 일반 함수 호출:
     * - "출력" 은 런타임 매크로를 사용
     * - "입력_정수", "입력_실수" 등은 런타임 함수를 사용
     */
    출력(gen, "%s(", 이름);

    인자 *인자p = n->데이터.호출.인자목록;
    bool 첫번째 = true;
    while (인자p) {
        if (!첫번째) 출력(gen, ", ");
        생성_표현식(gen, 인자p->값);
        첫번째 = false;
        인자p = 인자p->다음;
    }

    출력(gen, ")");
}

/* ===== 이항 연산 생성 ===== */

static void 생성_이항연산(코드생성기 *gen, 노드 *n) {
    출력(gen, "(");
    생성_표현식(gen, n->데이터.이항연산.왼쪽);
    출력(gen, " %s ", 연산자_문자열(n->데이터.이항연산.연산자));
    생성_표현식(gen, n->데이터.이항연산.오른쪽);
    출력(gen, ")");
}

/* ===== 단항 연산 생성 ===== */

static void 생성_단항연산(코드생성기 *gen, 노드 *n) {
    출력(gen, "(%s", 연산자_문자열(n->데이터.단항연산.연산자));
    생성_표현식(gen, n->데이터.단항연산.피연산자);
    출력(gen, ")");
}

/* ===== 멤버 접근 생성 ===== */

static void 생성_멤버접근(코드생성기 *gen, 노드 *n) {
    생성_표현식(gen, n->데이터.멤버접근.대상);
    if (n->데이터.멤버접근.포인터) {
        출력(gen, "->%s", n->데이터.멤버접근.멤버이름);
    } else {
        출력(gen, ".%s", n->데이터.멤버접근.멤버이름);
    }
}

/* ===== 배열 접근 생성 ===== */

static void 생성_배열접근(코드생성기 *gen, 노드 *n) {
    생성_표현식(gen, n->데이터.배열접근.배열);
    출력(gen, "[");
    생성_표현식(gen, n->데이터.배열접근.인덱스);
    출력(gen, "]");
}

/* ===== 형변환 생성 ===== */

static void 생성_형변환(코드생성기 *gen, 노드 *n) {
    출력(gen, "(");
    생성_타입(gen, n->데이터.형변환.대상타입);
    출력(gen, ")(");
    생성_표현식(gen, n->데이터.형변환.값);
    출력(gen, ")");
}

/* ===== 크기 연산(sizeof) 생성 ===== */

static void 생성_크기연산(코드생성기 *gen, 노드 *n) {
    출력(gen, "sizeof(");
    /* 대상이 타입이면 타입으로 생성, 아니면 표현식으로 생성 */
    노드 *대상 = n->데이터.크기연산.대상;
    if (대상->종류 == 노드_기본타입 || 대상->종류 == 노드_참조타입 ||
        대상->종류 == 노드_배열타입 || 대상->종류 == 노드_묶음타입명) {
        생성_타입(gen, 대상);
    } else {
        생성_표현식(gen, 대상);
    }
    출력(gen, ")");
}

/* ===== 증감 연산 생성 ===== */

static void 생성_증감(코드생성기 *gen, 노드 *n) {
    const char *연산 = n->데이터.증감.증가 ? "++" : "--";
    if (n->데이터.증감.전위) {
        출력(gen, "%s", 연산);
        생성_표현식(gen, n->데이터.증감.대상);
    } else {
        생성_표현식(gen, n->데이터.증감.대상);
        출력(gen, "%s", 연산);
    }
}

/* ===== 파이프라인 생성 ===== */

static void 생성_파이프라인(코드생성기 *gen, 노드 *n) {
    /*
     * 파이프라인: 시작값 -어서 동사1 -어서 동사2 -다.
     * 생성: 동사2(동사1(시작값))
     *
     * 임시 변수를 사용하여 단계별로 처리한다.
     */
    int 시작번호 = gen->임시변수_번호;

    /* 첫 번째 임시 변수에 시작값 할당 */
    출력(gen, "({ ");  /* GCC statement expression 또는 대안으로 임시 변수 사용 */

    /* 순차적으로 각 파이프 단계를 적용 */
    /* 간단한 방식: 중첩 호출로 변환 */

    /* 단계 목록을 역순으로 수집 */
    파이프단계 *단계 = n->데이터.파이프라인.단계목록;
    int 단계수 = 0;
    파이프단계 *현재 = 단계;
    while (현재) {
        단계수++;
        현재 = 현재->다음;
    }

    /* 동적 배열로 단계들 수집 */
    파이프단계 **단계배열 = NULL;
    if (단계수 > 0) {
        단계배열 = (파이프단계 **)malloc(sizeof(파이프단계 *) * 단계수);
        현재 = 단계;
        for (int i = 0; i < 단계수; i++) {
            단계배열[i] = 현재;
            현재 = 현재->다음;
        }
    }

    /* 중첩 함수 호출 생성: f3(f2(f1(시작값))) */
    for (int i = 단계수 - 1; i >= 0; i--) {
        출력(gen, "%s(", 단계배열[i]->동사);
    }
    생성_표현식(gen, n->데이터.파이프라인.시작값);
    for (int i = 0; i < 단계수; i++) {
        /* 추가 인자가 있으면 출력 */
        인자 *추가인자 = 단계배열[i]->인자목록;
        while (추가인자) {
            출력(gen, ", ");
            생성_표현식(gen, 추가인자->값);
            추가인자 = 추가인자->다음;
        }
        출력(gen, ")");
    }

    출력(gen, "; })");

    if (단계배열) free(단계배열);

    gen->임시변수_번호 = 시작번호;
}

/* ===== 표현식 생성 (디스패치) ===== */

static void 생성_표현식(코드생성기 *gen, 노드 *n) {
    if (!n) return;
    if (gen->오류_발생) return;

    switch (n->종류) {
        case 노드_정수_리터럴:
            출력(gen, "%lld", n->데이터.정수_리터럴.값);
            break;

        case 노드_실수_리터럴:
            출력(gen, "%g", n->데이터.실수_리터럴.값);
            break;

        case 노드_문자열_리터럴: {
            /* 문자열 안의 특수문자를 C 이스케이프로 재변환 */
            const char *s = n->데이터.문자열_리터럴.값;
            출력(gen, "\"");
            for (; *s; s++) {
                switch (*s) {
                case '\n': 출력(gen, "\\n"); break;
                case '\t': 출력(gen, "\\t"); break;
                case '\r': 출력(gen, "\\r"); break;
                case '\\': 출력(gen, "\\\\"); break;
                case '"':  출력(gen, "\\\""); break;
                case '\0': 출력(gen, "\\0"); break;
                default:   fprintf(gen->출력, "%c", *s); break;
                }
            }
            출력(gen, "\"");
            break;
        }

        case 노드_문자_리터럴:
            출력(gen, "'%s'", n->데이터.문자_리터럴.값);
            break;

        case 노드_참거짓_리터럴:
            출력(gen, "%d", n->데이터.참거짓_리터럴.값 ? 1 : 0);
            break;

        case 노드_없음_리터럴:
            출력(gen, "NULL");
            break;

        case 노드_식별자:
            출력(gen, "%s", n->데이터.식별자.이름);
            break;

        case 노드_이항연산:
            생성_이항연산(gen, n);
            break;

        case 노드_단항연산:
            생성_단항연산(gen, n);
            break;

        case 노드_호출:
            생성_호출(gen, n);
            break;

        case 노드_멤버접근:
            생성_멤버접근(gen, n);
            break;

        case 노드_배열접근:
            생성_배열접근(gen, n);
            break;

        case 노드_대입:
            생성_대입(gen, n);
            break;

        case 노드_형변환:
            생성_형변환(gen, n);
            break;

        case 노드_주소참조:
            출력(gen, "(&");
            생성_표현식(gen, n->데이터.참조연산.대상);
            출력(gen, ")");
            break;

        case 노드_역참조:
            출력(gen, "(*");
            생성_표현식(gen, n->데이터.참조연산.대상);
            출력(gen, ")");
            break;

        case 노드_크기:
            생성_크기연산(gen, n);
            break;

        case 노드_파이프라인:
            생성_파이프라인(gen, n);
            break;

        case 노드_묶음_리터럴:
            출력(gen, "{ ");
            for (int i = 0; i < n->데이터.묶음_리터럴.필드_수; i++) {
                if (i > 0) 출력(gen, ", ");
                출력(gen, ".%s = ", n->데이터.묶음_리터럴.필드이름목록[i]);
                생성_표현식(gen, n->데이터.묶음_리터럴.필드값목록[i]);
            }
            출력(gen, " }");
            break;

        case 노드_배열_리터럴:
            출력(gen, "{ ");
            for (int i = 0; i < n->데이터.배열_리터럴.원소_수; i++) {
                if (i > 0) 출력(gen, ", ");
                생성_표현식(gen, n->데이터.배열_리터럴.원소목록[i]);
            }
            출력(gen, " }");
            break;

        case 노드_증감:
            생성_증감(gen, n);
            break;

        case 노드_삼항:
            출력(gen, "(");
            생성_표현식(gen, n->데이터.삼항.조건);
            출력(gen, " ? ");
            생성_표현식(gen, n->데이터.삼항.참값);
            출력(gen, " : ");
            생성_표현식(gen, n->데이터.삼항.거짓값);
            출력(gen, ")");
            break;

        case 노드_가변인자:
            출력(gen, "va_arg(%s, ", n->데이터.가변인자.목록이름);
            생성_타입(gen, n->데이터.가변인자.타입);
            출력(gen, ")");
            break;

        default:
            오류_설정(gen, "표현식이 아닌 노드를 표현식으로 사용: %d", n->종류);
            출력(gen, "/* 표현식 오류 */0");
            break;
    }
}

/* ===== 갈래문 (switch) 생성 ===== */

static void 생성_갈래문(코드생성기 *gen, 노드 *n) {
    들여쓰기(gen);
    출력(gen, "switch (");
    생성_표현식(gen, n->데이터.갈래문.대상);
    출력(gen, ") {\n");

    갈래경우 *경우 = n->데이터.갈래문.경우목록;
    while (경우) {
        if (경우->값) {
            들여쓰기(gen);
            출력(gen, "case ");
            생성_표현식(gen, 경우->값);
            출력(gen, ": {\n");
        } else {
            들여쓰기(gen);
            출력(gen, "default: {\n");
        }

        gen->들여쓰기_깊이++;
        for (int i = 0; i < 경우->문장_수; i++) {
            생성_문장(gen, 경우->문장목록[i]);
        }
        /* 자동 break 삽입 (fall-through 방지) */
        줄출력(gen, "break;");
        gen->들여쓰기_깊이--;

        들여쓰기(gen);
        출력(gen, "}\n");

        경우 = 경우->다음;
    }

    들여쓰기(gen);
    출력(gen, "}\n");
}

/* ===== 문장 생성 (디스패치) ===== */

static void 생성_문장(코드생성기 *gen, 노드 *n) {
    if (!n) return;
    if (gen->오류_발생) return;

    switch (n->종류) {
        case 노드_변수선언:
            생성_변수선언(gen, n);
            break;

        case 노드_조건문:
            생성_조건문(gen, n);
            break;

        case 노드_동안반복:
            생성_동안반복(gen, n);
            break;

        case 노드_반복하기:
            생성_반복하기(gen, n);
            break;

        case 노드_이동문:
            줄출력(gen, "goto %s;", n->데이터.이동문.레이블);
            break;

        case 노드_레이블:
            /* 레이블은 들여쓰기 무시하고 왼쪽 정렬 */
            출력(gen, "%s:\n", n->데이터.레이블.이름);
            if (n->데이터.레이블.문장)
                생성_문장(gen, n->데이터.레이블.문장);
            break;

        case 노드_범위반복:
            생성_범위반복(gen, n);
            break;

        case 노드_반복문:
            생성_반복문(gen, n);
            break;

        case 노드_반환문:
            생성_반환문(gen, n);
            break;

        case 노드_탈출문:
            줄출력(gen, "break;");
            break;

        case 노드_계속문:
            줄출력(gen, "continue;");
            break;

        case 노드_갈래문:
            생성_갈래문(gen, n);
            break;

        case 노드_가변시작:
            줄출력(gen, "va_start(%s, %s);",
                n->데이터.가변시작.목록이름,
                n->데이터.가변시작.매개변수이름);
            break;

        case 노드_가변끝:
            줄출력(gen, "va_end(%s);", n->데이터.가변끝.목록이름);
            break;

        case 노드_전처리_만약정의:
        case 노드_전처리_만약:
        case 노드_전처리_아니면:
        case 노드_전처리_끝:
            생성_전처리(gen, n);
            break;

        case 노드_블록:
            들여쓰기(gen);
            생성_블록(gen, n);
            출력(gen, "\n");
            break;

        case 노드_표현식문:
            들여쓰기(gen);
            생성_표현식(gen, n->데이터.표현식문.표현식);
            출력(gen, ";\n");
            break;

        /* 표현식 노드가 문장 위치에 올 수 있음 (대입, 호출 등) */
        case 노드_대입:
            들여쓰기(gen);
            생성_대입(gen, n);
            출력(gen, ";\n");
            break;

        case 노드_호출:
            들여쓰기(gen);
            생성_호출(gen, n);
            출력(gen, ";\n");
            break;

        default:
            /* 그 외 표현식이 문장으로 올 수 있음 */
            들여쓰기(gen);
            생성_표현식(gen, n);
            출력(gen, ";\n");
            break;
    }
}

/* ===== 선언 생성 (디스패치) ===== */

static void 생성_선언(코드생성기 *gen, 노드 *n) {
    if (!n) return;
    if (gen->오류_발생) return;

    switch (n->종류) {
        case 노드_함수정의:
            생성_함수정의(gen, n);
            break;

        case 노드_변수선언:
            생성_변수선언(gen, n);
            break;

        case 노드_묶음정의:
            생성_묶음정의(gen, n);
            break;

        case 노드_나열정의:
            생성_나열정의(gen, n);
            break;

        case 노드_합침정의:
            생성_합침정의(gen, n);
            break;

        case 노드_별칭정의:
            별칭이름_등록(gen, n->데이터.별칭정의.이름);
            if (n->데이터.별칭정의.원래타입 &&
                n->데이터.별칭정의.원래타입->종류 == 노드_함수포인터타입) {
                /* typedef 반환타입 (*별칭이름)(매개변수타입들); */
                출력(gen, "typedef ");
                생성_함수포인터_선언(gen, n->데이터.별칭정의.원래타입,
                                     n->데이터.별칭정의.이름);
                출력(gen, ";\n\n");
            } else {
                출력(gen, "typedef ");
                생성_타입(gen, n->데이터.별칭정의.원래타입);
                출력(gen, " %s;\n\n", n->데이터.별칭정의.이름);
            }
            break;

        case 노드_매크로정의:
            if (n->데이터.매크로정의.값)
                출력(gen, "#define %s %s\n", n->데이터.매크로정의.이름,
                     n->데이터.매크로정의.값);
            else
                출력(gen, "#define %s\n", n->데이터.매크로정의.이름);
            break;

        case 노드_전처리_만약정의:
        case 노드_전처리_만약:
        case 노드_전처리_아니면:
        case 노드_전처리_끝:
            생성_전처리(gen, n);
            break;

        default:
            오류_설정(gen, "최상위에 올 수 없는 노드: %d", n->종류);
            break;
    }
}

/* ===== 전처리 지시문 생성 ===== */

static void 생성_전처리(코드생성기 *gen, 노드 *n) {
    switch (n->종류) {
        case 노드_전처리_만약정의:
            if (n->데이터.전처리.인자[0] == '!') {
                출력(gen, "#ifndef %s\n", n->데이터.전처리.인자 + 1);
            } else {
                출력(gen, "#ifdef %s\n", n->데이터.전처리.인자);
            }
            break;
        case 노드_전처리_만약:
            출력(gen, "#if %s\n", n->데이터.전처리.인자);
            break;
        case 노드_전처리_아니면:
            출력(gen, "#else\n");
            break;
        case 노드_전처리_끝:
            출력(gen, "#endif\n");
            break;
        default:
            break;
    }
}

/* ===== 노드 생성 (디스패치) ===== */

static void 생성_노드(코드생성기 *gen, 노드 *n) {
    if (!n) return;

    switch (n->종류) {
        case 노드_함수정의:
        case 노드_변수선언:
        case 노드_묶음정의:
        case 노드_나열정의:
        case 노드_합침정의:
        case 노드_별칭정의:
        case 노드_매크로정의:
            생성_선언(gen, n);
            break;

        case 노드_전처리_만약정의:
        case 노드_전처리_만약:
        case 노드_전처리_아니면:
        case 노드_전처리_끝:
            생성_전처리(gen, n);
            break;

        default:
            생성_문장(gen, n);
            break;
    }
}

/* ===== 메인 코드 생성 진입점 ===== */

bool 코드_생성(코드생성기 *gen, 노드 *프로그램) {
    if (!프로그램 || 프로그램->종류 != 노드_프로그램) {
        오류_설정(gen, "프로그램 노드가 필요합니다");
        return false;
    }

    /* 1. 헤더 주석 및 #include */
    출력_헤더(gen);

    /* 2. 런타임 함수 */
    출력_런타임(gen);

    /* 3. 묶음(struct) 및 나열(enum) 정의 먼저 */
    for (int i = 0; i < 프로그램->데이터.프로그램.선언_수; i++) {
        노드 *선언 = 프로그램->데이터.프로그램.선언목록[i];
        if (선언->종류 == 노드_묶음정의) {
            생성_묶음정의(gen, 선언);
        } else if (선언->종류 == 노드_합침정의) {
            생성_합침정의(gen, 선언);
        } else if (선언->종류 == 노드_나열정의) {
            생성_나열정의(gen, 선언);
        } else if (선언->종류 == 노드_별칭정의) {
            별칭이름_등록(gen, 선언->데이터.별칭정의.이름);
            if (선언->데이터.별칭정의.원래타입 &&
                선언->데이터.별칭정의.원래타입->종류 == 노드_함수포인터타입) {
                출력(gen, "typedef ");
                생성_함수포인터_선언(gen, 선언->데이터.별칭정의.원래타입,
                                     선언->데이터.별칭정의.이름);
                출력(gen, ";\n\n");
            } else {
                출력(gen, "typedef ");
                생성_타입(gen, 선언->데이터.별칭정의.원래타입);
                출력(gen, " %s;\n\n", 선언->데이터.별칭정의.이름);
            }
        } else if (선언->종류 == 노드_매크로정의) {
            if (선언->데이터.매크로정의.값)
                출력(gen, "#define %s %s\n", 선언->데이터.매크로정의.이름,
                     선언->데이터.매크로정의.값);
            else
                출력(gen, "#define %s\n", 선언->데이터.매크로정의.이름);
        }
    }

    /* 4. 전역 변수 선언 */
    for (int i = 0; i < 프로그램->데이터.프로그램.선언_수; i++) {
        노드 *선언 = 프로그램->데이터.프로그램.선언목록[i];
        if (선언->종류 == 노드_변수선언) {
            생성_변수선언(gen, 선언);
        }
    }

    /* 5. 함수 전방 선언 */
    출력(gen, "/* 함수 전방 선언 */\n");
    for (int i = 0; i < 프로그램->데이터.프로그램.선언_수; i++) {
        노드 *선언 = 프로그램->데이터.프로그램.선언목록[i];
        if (선언->종류 == 노드_함수정의) {
            생성_함수_전방선언(gen, 선언);
        }
    }
    출력(gen, "\n");

    /* 6. 함수 정의 */
    for (int i = 0; i < 프로그램->데이터.프로그램.선언_수; i++) {
        노드 *선언 = 프로그램->데이터.프로그램.선언목록[i];
        if (선언->종류 == 노드_함수정의) {
            생성_함수정의(gen, 선언);
        }
    }

    return !gen->오류_발생;
}
