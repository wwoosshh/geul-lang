/*
 * 주.c - 글 컴파일러 진입점
 *
 * 사용법: 글cc [옵션] <소스파일.글>
 *   -토큰        : 토큰 목록만 출력 (렉서 테스트)
 *   -구문        : AST 트리 출력 (파서 테스트)
 *   --emit-c     : C 코드만 생성 (컴파일하지 않음)
 *   -출력 파일   : 출력 파일 경로
 *   -도움        : 도움말 표시
 */
#include "유니코드.h"
#include "토큰.h"
#include "형태소분석기.h"
#include "구문분석기.h"
#include "구문트리.h"
#include "코드생성기.h"
#include "llvm생성기.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifdef _WIN32
#include <windows.h>
#include <io.h>
#include <fcntl.h>

/* Windows에서 UTF-8 경로로 파일 열기 */
static FILE *utf8_fopen(const char *경로, const char *모드) {
    int wpath_len = MultiByteToWideChar(CP_UTF8, 0, 경로, -1, NULL, 0);
    int wmode_len = MultiByteToWideChar(CP_UTF8, 0, 모드, -1, NULL, 0);
    wchar_t *wpath = (wchar_t *)malloc(wpath_len * sizeof(wchar_t));
    wchar_t *wmode = (wchar_t *)malloc(wmode_len * sizeof(wchar_t));
    MultiByteToWideChar(CP_UTF8, 0, 경로, -1, wpath, wpath_len);
    MultiByteToWideChar(CP_UTF8, 0, 모드, -1, wmode, wmode_len);
    FILE *f = _wfopen(wpath, wmode);
    free(wpath);
    free(wmode);
    return f;
}

/* argv를 UTF-8로 변환 */
static char *argv_to_utf8(const char *arg) {
    /* 시스템 코드페이지 → 와이드 → UTF-8 */
    int wlen = MultiByteToWideChar(CP_ACP, 0, arg, -1, NULL, 0);
    wchar_t *warg = (wchar_t *)malloc(wlen * sizeof(wchar_t));
    MultiByteToWideChar(CP_ACP, 0, arg, -1, warg, wlen);
    int ulen = WideCharToMultiByte(CP_UTF8, 0, warg, -1, NULL, 0, NULL, NULL);
    char *utf8 = (char *)malloc(ulen);
    WideCharToMultiByte(CP_UTF8, 0, warg, -1, utf8, ulen, NULL, NULL);
    free(warg);
    return utf8;
}
#else
static FILE *utf8_fopen(const char *경로, const char *모드) {
    return fopen(경로, 모드);
}
static char *argv_to_utf8(const char *arg) {
    return strdup(arg);
}
#endif

typedef enum {
    모드_토큰,       /* 렉서만 실행, 토큰 출력 */
    모드_구문,       /* 파서까지 실행, AST 출력 */
    모드_C코드,      /* C 코드 생성만 (--emit-c) */
    모드_LLVM,       /* LLVM IR 생성만 (--emit-llvm) */
    모드_컴파일,     /* C 백엔드 컴파일 */
    모드_네이티브,   /* LLVM 백엔드 네이티브 컴파일 (기본) */
} 실행모드;

/* 파일 전체를 읽어 버퍼로 반환 */
static char *파일_읽기(const char *경로, size_t *길이) {
    FILE *f = fopen(경로, "rb");
    if (!f) {
        fprintf(stderr, "오류: 파일을 열 수 없습니다: %s\n", 경로);
        return NULL;
    }

    fseek(f, 0, SEEK_END);
    long 크기 = ftell(f);
    fseek(f, 0, SEEK_SET);

    char *버퍼 = (char *)malloc(크기 + 1);
    size_t 읽은수 = fread(버퍼, 1, 크기, f);
    버퍼[읽은수] = '\0';
    fclose(f);

    /* UTF-8 BOM 제거 */
    char *시작 = 버퍼;
    if (읽은수 >= 3 && (unsigned char)버퍼[0] == 0xEF &&
        (unsigned char)버퍼[1] == 0xBB && (unsigned char)버퍼[2] == 0xBF) {
        시작 = 버퍼 + 3;
        읽은수 -= 3;
    }

    /* NFC 정규화 */
    읽은수 = 한글_nfc_정규화(시작, 읽은수);

    if (시작 != 버퍼) {
        memmove(버퍼, 시작, 읽은수 + 1);
    }

    *길이 = 읽은수;
    return 버퍼;
}

/* 전방 선언 */
static char *디렉토리_추출(const char *경로);

/* ===== 포함(include) 전처리기 ===== */

/*
 * 소스에서 '포함 "파일"' 지시문을 찾아 해당 파일의 내용으로 대체한다.
 * 검색 순서: 1) 소스 파일과 같은 디렉토리 2) 컴파일러 실행파일 옆의 표준/ 디렉토리
 *
 * 재귀 포함 지원: 포함된 파일 내의 포함 지시문도 처리한다.
 * 중복 방지: 같은 파일은 한 번만 포함한다.
 */

/* 포함된 파일 경로 추적 (중복 방지) */
#define 최대_포함_수 256
static char *포함된_파일목록[최대_포함_수];
static int 포함된_파일_수 = 0;
static int 포함_깊이 = 0;
#define 최대_포함_깊이 32

/* 정규화된 경로로 중복 확인 */
static bool 이미_포함됨(const char *경로) {
    for (int i = 0; i < 포함된_파일_수; i++) {
        if (strcmp(포함된_파일목록[i], 경로) == 0) return true;
    }
    return false;
}

static void 포함_등록(const char *경로) {
    if (포함된_파일_수 < 최대_포함_수) {
        포함된_파일목록[포함된_파일_수++] = strdup(경로);
    }
}

static void 포함_목록_해제(void) {
    for (int i = 0; i < 포함된_파일_수; i++) {
        free(포함된_파일목록[i]);
        포함된_파일목록[i] = NULL;
    }
    포함된_파일_수 = 0;
    포함_깊이 = 0;
}

/* 파일을 찾아 열기 (여러 검색 경로 시도) */
static FILE *포함_파일_찾기(const char *경로,
                             const char *소스_디렉토리,
                             const char *컴파일러_디렉토리,
                             char *결과_경로, size_t 결과_경로_크기) {
    FILE *f = NULL;

    /* 1) 소스 디렉토리 기준 */
    snprintf(결과_경로, 결과_경로_크기, "%s%s", 소스_디렉토리, 경로);
    f = utf8_fopen(결과_경로, "rb");
    if (f) return f;

    /* 2) 소스 디렉토리의 상위 */
    snprintf(결과_경로, 결과_경로_크기, "%s../%s", 소스_디렉토리, 경로);
    f = utf8_fopen(결과_경로, "rb");
    if (f) return f;

    /* 3) 컴파일러 디렉토리 기준 */
    if (컴파일러_디렉토리[0]) {
        snprintf(결과_경로, 결과_경로_크기, "%s%s", 컴파일러_디렉토리, 경로);
        f = utf8_fopen(결과_경로, "rb");
        if (f) return f;
    }

    /* 4) 컴파일러 상위 */
    if (컴파일러_디렉토리[0]) {
        snprintf(결과_경로, 결과_경로_크기, "%s../%s", 컴파일러_디렉토리, 경로);
        f = utf8_fopen(결과_경로, "rb");
        if (f) return f;
    }

    /* 5) 컴파일러 2단계 상위 (build/ 안에서 실행 시) */
    if (컴파일러_디렉토리[0]) {
        snprintf(결과_경로, 결과_경로_크기, "%s../../%s", 컴파일러_디렉토리, 경로);
        f = utf8_fopen(결과_경로, "rb");
        if (f) return f;
    }

    return NULL;
}

static char *포함_전처리(const char *소스, size_t 길이,
                          const char *소스_디렉토리,
                          const char *컴파일러_디렉토리,
                          size_t *결과_길이) {
    /* 결과 버퍼 */
    size_t 용량 = 길이 * 2 + 1024;
    char *결과 = (char *)malloc(용량);
    size_t 결과_위치 = 0;

    const char *p = 소스;
    const char *끝 = 소스 + 길이;

    while (p < 끝) {
        /* 줄의 시작 부분에서 "포함" 키워드 검색 */
        /* UTF-8로 "포함" = 0xED 0x8F 0xAC 0xED 0x95 0xA8 (6 bytes) */
        const char *포함_시작 = NULL;

        /* 간단한 방식: 각 줄을 검사 */
        const char *줄_끝 = p;
        while (줄_끝 < 끝 && *줄_끝 != '\n') 줄_끝++;

        /* 공백을 건너뛴 후 "포함"으로 시작하는지 확인 */
        const char *줄_시작 = p;
        while (줄_시작 < 줄_끝 && (*줄_시작 == ' ' || *줄_시작 == '\t')) 줄_시작++;

        /* "포함" 확인 (UTF-8: 0xED8FAC ED95A8) */
        if (줄_끝 - 줄_시작 > 6 &&
            (unsigned char)줄_시작[0] == 0xED && (unsigned char)줄_시작[1] == 0x8F &&
            (unsigned char)줄_시작[2] == 0xAC && (unsigned char)줄_시작[3] == 0xED &&
            (unsigned char)줄_시작[4] == 0x95 && (unsigned char)줄_시작[5] == 0xA8) {

            포함_시작 = 줄_시작 + 6;
            /* 공백 건너뛰기 */
            while (포함_시작 < 줄_끝 && (*포함_시작 == ' ' || *포함_시작 == '\t'))
                포함_시작++;

            /* 따옴표로 둘러싸인 파일 경로 추출 */
            if (포함_시작 < 줄_끝 && *포함_시작 == '"') {
                포함_시작++;
                const char *경로_끝 = 포함_시작;
                while (경로_끝 < 줄_끝 && *경로_끝 != '"') 경로_끝++;

                if (경로_끝 > 포함_시작) {
                    size_t 경로_길이 = 경로_끝 - 포함_시작;
                    char 경로[2048];
                    memcpy(경로, 포함_시작, 경로_길이);
                    경로[경로_길이] = '\0';

                    /* 파일 찾기 */
                    char 전체경로[4096];
                    FILE *f = 포함_파일_찾기(경로, 소스_디렉토리,
                                              컴파일러_디렉토리,
                                              전체경로, sizeof(전체경로));

                    if (f) {
                        /* 중복 포함 방지 */
                        if (이미_포함됨(전체경로)) {
                            fclose(f);
                            p = (줄_끝 < 끝) ? 줄_끝 + 1 : 끝;
                            continue;
                        }

                        /* 포함 깊이 검사 */
                        if (포함_깊이 >= 최대_포함_깊이) {
                            fclose(f);
                            fprintf(stderr, "오류: 포함 깊이 초과 (%d단계): %s\n",
                                    최대_포함_깊이, 경로);
                            p = (줄_끝 < 끝) ? 줄_끝 + 1 : 끝;
                            continue;
                        }

                        포함_등록(전체경로);

                        fseek(f, 0, SEEK_END);
                        long 파일크기 = ftell(f);
                        fseek(f, 0, SEEK_SET);

                        char *포함내용 = (char *)malloc(파일크기 + 1);
                        size_t 읽음 = fread(포함내용, 1, 파일크기, f);
                        포함내용[읽음] = '\0';
                        fclose(f);

                        /* UTF-8 BOM 제거 */
                        char *내용시작 = 포함내용;
                        if (읽음 >= 3 && (unsigned char)포함내용[0] == 0xEF &&
                            (unsigned char)포함내용[1] == 0xBB &&
                            (unsigned char)포함내용[2] == 0xBF) {
                            내용시작 = 포함내용 + 3;
                            읽음 -= 3;
                        }

                        /* NFC 정규화 */
                        읽음 = 한글_nfc_정규화(내용시작, 읽음);

                        /* 재귀 포함: 포함된 파일 내의 포함 지시문도 처리 */
                        char *포함_디렉 = 디렉토리_추출(전체경로);
                        size_t 재귀_길이;
                        포함_깊이++;
                        char *재귀_결과 = 포함_전처리(내용시작, 읽음,
                                                        포함_디렉,
                                                        컴파일러_디렉토리,
                                                        &재귀_길이);
                        포함_깊이--;
                        free(포함_디렉);
                        free(포함내용);

                        /* 결과 버퍼에 재귀 처리된 내용 추가 */
                        while (결과_위치 + 재귀_길이 + 2 > 용량) {
                            용량 *= 2;
                            결과 = (char *)realloc(결과, 용량);
                        }
                        memcpy(결과 + 결과_위치, 재귀_결과, 재귀_길이);
                        결과_위치 += 재귀_길이;
                        결과[결과_위치++] = '\n';

                        free(재귀_결과);

                        /* 이 줄을 건너뛰고 다음 줄로 */
                        p = (줄_끝 < 끝) ? 줄_끝 + 1 : 끝;
                        continue;
                    } else {
                        fprintf(stderr, "경고: 포함 파일을 찾을 수 없습니다: %s\n", 경로);
                    }
                }
            }
        }

        /* 일반 줄: 그대로 복사 */
        size_t 줄_크기 = (줄_끝 < 끝) ? (size_t)(줄_끝 - p + 1) : (size_t)(줄_끝 - p);
        while (결과_위치 + 줄_크기 + 1 > 용량) {
            용량 *= 2;
            결과 = (char *)realloc(결과, 용량);
        }
        memcpy(결과 + 결과_위치, p, 줄_크기);
        결과_위치 += 줄_크기;
        p = (줄_끝 < 끝) ? 줄_끝 + 1 : 끝;
    }

    결과[결과_위치] = '\0';
    *결과_길이 = 결과_위치;
    return 결과;
}

/* 경로에서 확장자를 제거한 기본 이름을 반환 (새 문자열 할당) */
static char *기본이름_추출(const char *경로) {
    /* 마지막 디렉토리 구분자 이후 */
    const char *이름 = 경로;
    for (const char *p = 경로; *p; p++) {
        if (*p == '/' || *p == '\\') 이름 = p + 1;
    }

    /* 확장자 제거 */
    const char *점 = NULL;
    for (const char *p = 이름; *p; p++) {
        if (*p == '.') 점 = p;
    }

    size_t 길이;
    if (점 && 점 > 이름) {
        길이 = 점 - 이름;
    } else {
        길이 = strlen(이름);
    }

    char *결과 = (char *)malloc(길이 + 1);
    memcpy(결과, 이름, 길이);
    결과[길이] = '\0';
    return 결과;
}

/* 경로에서 디렉토리 부분을 반환 (새 문자열 할당, 끝에 구분자 포함) */
static char *디렉토리_추출(const char *경로) {
    const char *마지막구분자 = NULL;
    for (const char *p = 경로; *p; p++) {
        if (*p == '/' || *p == '\\') 마지막구분자 = p;
    }

    if (마지막구분자) {
        size_t 길이 = 마지막구분자 - 경로 + 1;
        char *결과 = (char *)malloc(길이 + 1);
        memcpy(결과, 경로, 길이);
        결과[길이] = '\0';
        return 결과;
    } else {
        char *결과 = (char *)malloc(1);
        결과[0] = '\0';
        return 결과;
    }
}

/* 토큰 모드: 렉서 테스트 */
static int 토큰_모드_실행(const char *소스, size_t 길이, const char *파일명) {
    형태소분석기 분석기;
    분석기_초기화(&분석기, 소스, 길이, 파일명);

    printf("=== 토큰 목록 ===\n");
    printf("%-6s %-20s %-20s %s\n", "줄:열", "종류", "텍스트", "역할/기능");
    printf("--------------------------------------------------------------\n");

    int 토큰수 = 0;
    while (true) {
        토큰 t = 다음_토큰(&분석기);
        if (t.종류 == 토큰_파일끝) break;

        char 역할_정보[64] = "";
        if (t.역할 != 역할_없음) {
            snprintf(역할_정보, sizeof(역할_정보), "역할:%d", t.역할);
        }
        if (t.기능 != 어미_없음) {
            snprintf(역할_정보, sizeof(역할_정보), "기능:%d", t.기능);
        }

        printf("%3d:%-3d %-20s %-20s %s\n",
               t.위치.줄, t.위치.열,
               토큰_이름(t.종류),
               t.텍스트 ? t.텍스트 : "",
               역할_정보);
        토큰수++;

        if (t.텍스트) free(t.텍스트);
    }

    printf("--------------------------------------------------------------\n");
    printf("총 %d개 토큰\n", 토큰수);

    if (분석기.오류_발생) {
        fprintf(stderr, "%s\n", 분석기.오류_메시지);
        return 1;
    }
    return 0;
}

/* 구문 모드: 파서 테스트 */
static int 구문_모드_실행(const char *소스, size_t 길이, const char *파일명) {
    형태소분석기 분석기;
    분석기_초기화(&분석기, 소스, 길이, 파일명);

    구문분석기 파서;
    파서_초기화(&파서, &분석기);

    노드 *프로그램 = 프로그램_파싱(&파서);

    if (파서_오류있는가(&파서)) {
        파서_오류출력(&파서);
        노드_해제(프로그램);
        return 1;
    }

    printf("=== 구문 트리 (AST) ===\n");
    ast_출력(프로그램, 0);

    노드_해제(프로그램);
    return 0;
}

/* C 코드 생성: 소스를 파싱하여 C 파일로 출력 */
static int C코드_생성(const char *소스, size_t 길이, const char *파일명,
                      const char *c_경로) {
    형태소분석기 분석기;
    분석기_초기화(&분석기, 소스, 길이, 파일명);

    구문분석기 파서;
    파서_초기화(&파서, &분석기);

    노드 *프로그램 = 프로그램_파싱(&파서);

    if (파서_오류있는가(&파서)) {
        파서_오류출력(&파서);
        노드_해제(프로그램);
        return 1;
    }

    FILE *c_파일 = fopen(c_경로, "wb");
    if (!c_파일) {
        fprintf(stderr, "오류: C 파일을 생성할 수 없습니다: %s\n", c_경로);
        노드_해제(프로그램);
        return 1;
    }

    코드생성기 생성기;
    생성기_초기화(&생성기, c_파일);

    bool 성공 = 코드_생성(&생성기, 프로그램);

    fclose(c_파일);
    노드_해제(프로그램);

    if (!성공) {
        fprintf(stderr, "오류: C 코드 생성 실패: %s\n", 생성기.오류_메시지);
        return 1;
    }

    return 0;
}

/* C 컴파일러를 호출하여 .c 파일을 실행 파일로 컴파일 */
static int C컴파일_실행(const char *c_경로, const char *출력_경로) {
    char cmd[8192];
    int ret;

#ifdef _WIN32
    /* Windows: cl.exe (MSVC) 시도 - 전체 경로 및 포함/라이브러리 경로 지정 */
    snprintf(cmd, sizeof(cmd),
        "\"\"C:\\Program Files\\Microsoft Visual Studio\\2022\\Community"
        "\\VC\\Tools\\MSVC\\14.44.35207\\bin\\Hostx64\\x64\\cl.exe\" "
        "/utf-8 /nologo /std:c11 /GS- "
        "/I\"C:\\Program Files\\Microsoft Visual Studio\\2022\\Community"
        "\\VC\\Tools\\MSVC\\14.44.35207\\include\" "
        "/I\"C:\\Program Files (x86)\\Windows Kits\\10\\Include"
        "\\10.0.26100.0\\ucrt\" "
        "/I\"C:\\Program Files (x86)\\Windows Kits\\10\\Include"
        "\\10.0.26100.0\\um\" "
        "/I\"C:\\Program Files (x86)\\Windows Kits\\10\\Include"
        "\\10.0.26100.0\\shared\" "
        "/Fe:\"%s\" \"%s\" "
        "/link /STACK:16777216 "
        "/LIBPATH:\"C:\\Program Files\\Microsoft Visual Studio\\2022"
        "\\Community\\VC\\Tools\\MSVC\\14.44.35207\\lib\\x64\" "
        "/LIBPATH:\"C:\\Program Files (x86)\\Windows Kits\\10\\Lib"
        "\\10.0.26100.0\\ucrt\\x64\" "
        "/LIBPATH:\"C:\\Program Files (x86)\\Windows Kits\\10\\Lib"
        "\\10.0.26100.0\\um\\x64\"\"",
        출력_경로, c_경로);
    ret = system(cmd);
    if (ret == 0) return 0;

    /* cl.exe 실패 시 gcc 시도 */
    fprintf(stderr, "참고: cl.exe 실패, gcc 시도 중...\n");
    snprintf(cmd, sizeof(cmd),
        "gcc -Wall -std=c11 -finput-charset=UTF-8 -fexec-charset=UTF-8 "
        "-o \"%s\" \"%s\" 2>&1",
        출력_경로, c_경로);
    ret = system(cmd);
#else
    /* Linux/macOS: cc 사용 */
    snprintf(cmd, sizeof(cmd),
        "cc -Wall -std=c11 -o \"%s\" \"%s\" 2>&1",
        출력_경로, c_경로);
    ret = system(cmd);
#endif

    return ret;
}

/* 컴파일 모드: 전체 파이프라인 실행 */
static int 컴파일_모드_실행(const char *소스, size_t 길이,
                            const char *소스파일, const char *출력파일,
                            bool c_코드만) {
    /* C 파일 경로 생성: 소스 파일과 같은 디렉토리, 같은 기본 이름 + .c */
    char *디렉토리 = 디렉토리_추출(소스파일);
    char *기본이름 = 기본이름_추출(소스파일);

    size_t c_경로_길이 = strlen(디렉토리) + strlen(기본이름) + 3;
    char *c_경로 = (char *)malloc(c_경로_길이);
    snprintf(c_경로, c_경로_길이, "%s%s.c", 디렉토리, 기본이름);

    /* 출력 실행 파일 경로 결정 */
    char *출력_경로 = NULL;
    if (출력파일) {
        출력_경로 = strdup(출력파일);
    } else {
#ifdef _WIN32
        size_t 출력_길이 = strlen(디렉토리) + strlen(기본이름) + 5;
        출력_경로 = (char *)malloc(출력_길이);
        snprintf(출력_경로, 출력_길이, "%s%s.exe", 디렉토리, 기본이름);
#else
        size_t 출력_길이 = strlen(디렉토리) + strlen(기본이름) + 1;
        출력_경로 = (char *)malloc(출력_길이);
        snprintf(출력_경로, 출력_길이, "%s%s", 디렉토리, 기본이름);
#endif
    }

    /* 단계 1: C 코드 생성 */
    printf("컴파일 중: %s → %s\n", 소스파일, c_경로);

    int 결과 = C코드_생성(소스, 길이, 소스파일, c_경로);
    if (결과 != 0) {
        free(디렉토리);
        free(기본이름);
        free(c_경로);
        free(출력_경로);
        return 결과;
    }

    printf("C 코드 생성 완료\n");

    /* --emit-c 모드: C 파일만 생성하고 종료 */
    if (c_코드만) {
        printf("C 소스 파일: %s\n", c_경로);
        free(디렉토리);
        free(기본이름);
        free(c_경로);
        free(출력_경로);
        return 0;
    }

    /* 단계 2: C 컴파일러 호출 */
    printf("C 컴파일 중: %s → %s\n", c_경로, 출력_경로);

    결과 = C컴파일_실행(c_경로, 출력_경로);

    if (결과 == 0) {
        printf("컴파일 성공: %s\n", 출력_경로);
        /* 성공 시 임시 C 파일 삭제 */
        remove(c_경로);
    } else {
        fprintf(stderr, "오류: C 컴파일 실패 (종료 코드: %d)\n", 결과);
        fprintf(stderr, "생성된 C 파일이 보존됩니다: %s\n", c_경로);
    }

    free(디렉토리);
    free(기본이름);
    free(c_경로);
    free(출력_경로);
    return 결과 == 0 ? 0 : 1;
}

/* LLVM IR 생성 */
static int LLVM_IR_생성(const char *소스, size_t 길이, const char *파일명,
                        const char *ll_경로) {
    형태소분석기 분석기;
    분석기_초기화(&분석기, 소스, 길이, 파일명);

    구문분석기 파서;
    파서_초기화(&파서, &분석기);

    노드 *프로그램 = 프로그램_파싱(&파서);

    if (파서_오류있는가(&파서)) {
        파서_오류출력(&파서);
        노드_해제(프로그램);
        return 1;
    }

    FILE *ll_파일 = fopen(ll_경로, "wb");
    if (!ll_파일) {
        fprintf(stderr, "오류: LLVM IR 파일을 생성할 수 없습니다: %s\n", ll_경로);
        노드_해제(프로그램);
        return 1;
    }

    llvm생성기 생성기;
    llvm_생성기_초기화(&생성기, ll_파일);

    bool 성공 = llvm_코드_생성(&생성기, 프로그램);

    fclose(ll_파일);
    노드_해제(프로그램);

    if (!성공) {
        fprintf(stderr, "오류: LLVM IR 생성 실패: %s\n", 생성기.오류_메시지);
        return 1;
    }

    return 0;
}

/* LLVM 도구를 사용하여 .ll → .obj → .exe 컴파일 */
static int LLVM_컴파일_실행(const char *ll_경로, const char *출력_경로) {
    char cmd[8192];
    char obj_경로[2048];
    int ret;

    /* .ll → .obj (llc 사용) */
    size_t ll_len = strlen(ll_경로);
    strncpy(obj_경로, ll_경로, sizeof(obj_경로) - 1);
    if (ll_len > 3 && strcmp(ll_경로 + ll_len - 3, ".ll") == 0) {
        strcpy(obj_경로 + ll_len - 3, ".obj");
    } else {
        snprintf(obj_경로, sizeof(obj_경로), "%s.obj", ll_경로);
    }

    /* 방법 1: clang으로 직접 컴파일 (가장 간단) */
    snprintf(cmd, sizeof(cmd),
        "\"\"C:\\Program Files\\LLVM\\bin\\clang.exe\" -O2 -o \"%s\" \"%s\"\"",
        출력_경로, ll_경로);
    ret = system(cmd);
    if (ret == 0) return 0;

    /* 방법 2: llc + link.exe */
    snprintf(cmd, sizeof(cmd),
        "\"\"C:\\Program Files\\LLVM\\bin\\llc.exe\" -filetype=obj -mtriple=x86_64-pc-windows-msvc -O2 -o \"%s\" \"%s\"\"",
        obj_경로, ll_경로);
    ret = system(cmd);
    if (ret == 0) {
        /* link.exe로 링크 */
        snprintf(cmd, sizeof(cmd),
            "\"\"C:\\Program Files\\Microsoft Visual Studio\\2022\\Community"
            "\\VC\\Tools\\MSVC\\14.44.35207\\bin\\Hostx64\\x64\\link.exe\" "
            "/nologo /OUT:\"%s\" \"%s\" "
            "/DEFAULTLIB:libcmt "
            "/LIBPATH:\"C:\\Program Files\\Microsoft Visual Studio\\2022\\Community"
            "\\VC\\Tools\\MSVC\\14.44.35207\\lib\\x64\" "
            "/LIBPATH:\"C:\\Program Files (x86)\\Windows Kits\\10\\Lib"
            "\\10.0.26100.0\\ucrt\\x64\" "
            "/LIBPATH:\"C:\\Program Files (x86)\\Windows Kits\\10\\Lib"
            "\\10.0.26100.0\\um\\x64\"\"",
            출력_경로, obj_경로);
        ret = system(cmd);
        remove(obj_경로); /* 임시 .obj 삭제 */
        return ret;
    }

    fprintf(stderr, "오류: LLVM 도구(clang 또는 llc)를 찾을 수 없습니다.\n");
    fprintf(stderr, "LLVM을 설치해 주세요: winget install LLVM.LLVM\n");
    return 1;
}

/* 네이티브 컴파일 모드 (LLVM 백엔드) */
static int 네이티브_모드_실행(const char *소스, size_t 길이,
                              const char *소스파일, const char *출력파일,
                              bool ll_만) {
    char *디렉토리 = 디렉토리_추출(소스파일);
    char *기본이름 = 기본이름_추출(소스파일);

    size_t ll_경로_길이 = strlen(디렉토리) + strlen(기본이름) + 4;
    char *ll_경로 = (char *)malloc(ll_경로_길이);
    snprintf(ll_경로, ll_경로_길이, "%s%s.ll", 디렉토리, 기본이름);

    char *출력_경로 = NULL;
    if (출력파일) {
        출력_경로 = strdup(출력파일);
    } else {
#ifdef _WIN32
        size_t 출력_길이 = strlen(디렉토리) + strlen(기본이름) + 5;
        출력_경로 = (char *)malloc(출력_길이);
        snprintf(출력_경로, 출력_길이, "%s%s.exe", 디렉토리, 기본이름);
#else
        size_t 출력_길이 = strlen(디렉토리) + strlen(기본이름) + 1;
        출력_경로 = (char *)malloc(출력_길이);
        snprintf(출력_경로, 출력_길이, "%s%s", 디렉토리, 기본이름);
#endif
    }

    printf("LLVM IR 생성 중: %s → %s\n", 소스파일, ll_경로);

    int 결과 = LLVM_IR_생성(소스, 길이, 소스파일, ll_경로);
    if (결과 != 0) {
        free(디렉토리); free(기본이름); free(ll_경로); free(출력_경로);
        return 결과;
    }

    printf("LLVM IR 생성 완료\n");

    if (ll_만) {
        printf("LLVM IR 파일: %s\n", ll_경로);
        free(디렉토리); free(기본이름); free(ll_경로); free(출력_경로);
        return 0;
    }

    printf("네이티브 컴파일 중: %s → %s\n", ll_경로, 출력_경로);

    결과 = LLVM_컴파일_실행(ll_경로, 출력_경로);

    if (결과 == 0) {
        printf("컴파일 성공: %s\n", 출력_경로);
        remove(ll_경로);
    } else {
        fprintf(stderr, "LLVM IR 파일이 보존됩니다: %s\n", ll_경로);
    }

    free(디렉토리); free(기본이름); free(ll_경로); free(출력_경로);
    return 결과 == 0 ? 0 : 1;
}

/* 사용법 출력 */
static void 사용법(void) {
    printf("사용법: 글cc [옵션] <소스파일.글>\n");
    printf("\n옵션:\n");
    printf("  (기본)         컴파일 (.글 → .c → 실행파일)\n");
    printf("  --emit-c       C 코드만 생성 (.c)\n");
    printf("  --emit-llvm    LLVM IR만 생성 (.ll)\n");
    printf("  --tokens       토큰 목록 출력\n");
    printf("  --ast          구문 트리 출력\n");
    printf("  -o 파일        출력 파일 경로\n");
    printf("  --help         도움말\n");
    printf("\n예시:\n");
    printf("  글cc 인사.글                    컴파일 → 인사.exe\n");
    printf("  글cc 인사.글 -o 내프로그램.exe  출력 이름 지정\n");
    printf("  글cc --emit-c 인사.글           C 소스만 생성\n");
}

int main(int argc, char *argv[]) {
    실행모드 모드 = 모드_컴파일;  /* 기본: C 백엔드 컴파일 */
    const char *소스파일 = NULL;
    const char *출력파일 = NULL;

    /* 인자 파싱 */
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "-토큰") == 0 || strcmp(argv[i], "--tokens") == 0) {
            모드 = 모드_토큰;
        } else if (strcmp(argv[i], "-구문") == 0 || strcmp(argv[i], "--ast") == 0) {
            모드 = 모드_구문;
        } else if (strcmp(argv[i], "--emit-c") == 0) {
            모드 = 모드_C코드;
        } else if (strcmp(argv[i], "--emit-llvm") == 0) {
            모드 = 모드_LLVM;
        } else if (strcmp(argv[i], "--via-c") == 0) {
            모드 = 모드_컴파일;
        } else if (strcmp(argv[i], "-출력") == 0 || strcmp(argv[i], "-o") == 0) {
            if (i + 1 < argc) 출력파일 = argv[++i];
        } else if (strcmp(argv[i], "-도움") == 0 || strcmp(argv[i], "--help") == 0) {
            사용법();
            return 0;
        } else if (argv[i][0] != '-') {
            소스파일 = argv[i];
        } else {
            fprintf(stderr, "알 수 없는 옵션: %s\n", argv[i]);
            사용법();
            return 1;
        }
    }

    if (!소스파일) {
        fprintf(stderr, "오류: 소스 파일이 지정되지 않았습니다\n");
        사용법();
        return 1;
    }

    /* argv 경로를 UTF-8로 변환 */
    char *소스파일_utf8 = argv_to_utf8(소스파일);
    char *argv0_utf8 = argv_to_utf8(argv[0]);

    /* 파일 읽기 */
    size_t 길이;
    char *소스_원본 = 파일_읽기(소스파일, &길이);
    if (!소스_원본) { free(소스파일_utf8); free(argv0_utf8); return 1; }

    /* 포함(include) 전처리 */
    char *소스_디렉 = 디렉토리_추출(소스파일_utf8);
    char *컴파일러_디렉 = 디렉토리_추출(argv0_utf8);
    free(소스파일_utf8);
    free(argv0_utf8);
    size_t 전처리_길이;
    char *소스 = 포함_전처리(소스_원본, 길이, 소스_디렉, 컴파일러_디렉, &전처리_길이);
    free(소스_원본);
    free(소스_디렉);
    free(컴파일러_디렉);
    길이 = 전처리_길이;

    int 결과 = 0;

    switch (모드) {
    case 모드_토큰:
        결과 = 토큰_모드_실행(소스, 길이, 소스파일);
        break;
    case 모드_구문:
        결과 = 구문_모드_실행(소스, 길이, 소스파일);
        break;
    case 모드_C코드:
        printf("글cc 0.1 - 글 컴파일러\n");
        결과 = 컴파일_모드_실행(소스, 길이, 소스파일, 출력파일, true);
        break;
    case 모드_컴파일:
        printf("글cc 0.1 - 글 컴파일러\n");
        결과 = 컴파일_모드_실행(소스, 길이, 소스파일, 출력파일, false);
        break;
    case 모드_LLVM:
        printf("글cc 0.1 - 글 컴파일러 (LLVM)\n");
        결과 = 네이티브_모드_실행(소스, 길이, 소스파일, 출력파일, true);
        break;
    case 모드_네이티브:
        printf("글cc 0.1 - 글 컴파일러 (LLVM 네이티브)\n");
        결과 = 네이티브_모드_실행(소스, 길이, 소스파일, 출력파일, false);
        break;
    }

    free(소스);
    포함_목록_해제();
    return 결과;
}
