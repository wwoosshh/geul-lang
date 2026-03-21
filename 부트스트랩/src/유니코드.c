/*
 * 유니코드.c - UTF-8 인코딩 및 한글 유니코드 처리 구현
 */
#include "유니코드.h"
#include <string.h>
#include <stdlib.h>

#ifdef _MSC_VER
#include <malloc.h>
#define 스택할당(크기) _alloca(크기)
#else
#define 스택할당(크기) __builtin_alloca(크기)
#endif

/* ===== UTF-8 디코딩/인코딩 ===== */

코드포인트 utf8_디코딩(const char **src) {
    const unsigned char *p = (const unsigned char *)*src;
    코드포인트 cp;
    int 추가바이트;

    if (p[0] == 0) {
        return 0;
    }

    if (p[0] < 0x80) {
        /* 1바이트: 0xxxxxxx (ASCII) */
        cp = p[0];
        추가바이트 = 0;
    } else if ((p[0] & 0xE0) == 0xC0) {
        /* 2바이트: 110xxxxx 10xxxxxx */
        cp = p[0] & 0x1F;
        추가바이트 = 1;
    } else if ((p[0] & 0xF0) == 0xE0) {
        /* 3바이트: 1110xxxx 10xxxxxx 10xxxxxx (한글은 여기) */
        cp = p[0] & 0x0F;
        추가바이트 = 2;
    } else if ((p[0] & 0xF8) == 0xF0) {
        /* 4바이트: 11110xxx 10xxxxxx 10xxxxxx 10xxxxxx */
        cp = p[0] & 0x07;
        추가바이트 = 3;
    } else {
        /* 잘못된 UTF-8 */
        *src += 1;
        return 0xFFFD; /* 대체 문자 */
    }

    for (int i = 0; i < 추가바이트; i++) {
        if ((p[1 + i] & 0xC0) != 0x80) {
            /* 잘못된 연속 바이트 */
            *src += 1;
            return 0xFFFD;
        }
        cp = (cp << 6) | (p[1 + i] & 0x3F);
    }

    *src += 1 + 추가바이트;
    return cp;
}

int utf8_인코딩(코드포인트 cp, char *dst) {
    unsigned char *p = (unsigned char *)dst;

    if (cp < 0x80) {
        p[0] = (unsigned char)cp;
        return 1;
    } else if (cp < 0x800) {
        p[0] = 0xC0 | (cp >> 6);
        p[1] = 0x80 | (cp & 0x3F);
        return 2;
    } else if (cp < 0x10000) {
        p[0] = 0xE0 | (cp >> 12);
        p[1] = 0x80 | ((cp >> 6) & 0x3F);
        p[2] = 0x80 | (cp & 0x3F);
        return 3;
    } else if (cp < 0x110000) {
        p[0] = 0xF0 | (cp >> 18);
        p[1] = 0x80 | ((cp >> 12) & 0x3F);
        p[2] = 0x80 | ((cp >> 6) & 0x3F);
        p[3] = 0x80 | (cp & 0x3F);
        return 4;
    }

    /* 유효 범위 초과 */
    p[0] = 0xEF; p[1] = 0xBF; p[2] = 0xBD; /* U+FFFD */
    return 3;
}

size_t utf8_길이(const char *s) {
    size_t count = 0;
    while (*s) {
        if (utf8_시작바이트인가(*s)) count++;
        s++;
    }
    return count;
}

bool utf8_시작바이트인가(char c) {
    unsigned char uc = (unsigned char)c;
    /* 연속 바이트(10xxxxxx)가 아니면 시작 바이트 */
    return (uc & 0xC0) != 0x80;
}

/* ===== 한글 판별 함수 ===== */

bool 한글_음절인가(코드포인트 cp) {
    return cp >= 한글_음절_시작 && cp <= 한글_음절_끝;
}

bool 한글_자모인가(코드포인트 cp) {
    return (cp >= 한글_자모_시작 && cp <= 한글_자모_끝) ||
           (cp >= 한글_호환자모_시작 && cp <= 한글_호환자모_끝);
}

bool 한글인가(코드포인트 cp) {
    return 한글_음절인가(cp) || 한글_자모인가(cp);
}

bool 식별자_시작인가(코드포인트 cp) {
    return 한글인가(cp) || cp == '_' ||
           (cp >= 'a' && cp <= 'z') ||
           (cp >= 'A' && cp <= 'Z');
}

bool 식별자_문자인가(코드포인트 cp) {
    return 식별자_시작인가(cp) || 숫자인가(cp);
}

bool 숫자인가(코드포인트 cp) {
    return cp >= '0' && cp <= '9';
}

bool 공백인가(코드포인트 cp) {
    return cp == ' ' || cp == '\t' || cp == '\r' || cp == '\n' ||
           cp == 0x3000; /* 전각 공백 */
}

/* ===== 한글 음절 분해 ===== */

/*
 * 한글 음절의 유니코드 공식:
 * 코드포인트 = 0xAC00 + (초성 * 21 + 중성) * 28 + 종성
 *
 * 초성(19개): ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ
 * 중성(21개): ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ
 * 종성(28개): (없음)ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ
 */

한글_분해 음절_분해(코드포인트 cp) {
    한글_분해 결과 = { -1, -1, -1 };

    if (!한글_음절인가(cp)) return 결과;

    uint32_t 오프셋 = cp - 한글_음절_시작;
    결과.종성 = 오프셋 % 종성_개수;
    오프셋 /= 종성_개수;
    결과.중성 = 오프셋 % 중성_개수;
    결과.초성 = 오프셋 / 중성_개수;

    return 결과;
}

코드포인트 음절_합성(int 초성, int 중성, int 종성) {
    if (초성 < 0 || 초성 >= 초성_개수) return 0xFFFD;
    if (중성 < 0 || 중성 >= 중성_개수) return 0xFFFD;
    if (종성 < 0 || 종성 >= 종성_개수) return 0xFFFD;

    return 한글_음절_시작 + (초성 * 중성_개수 + 중성) * 종성_개수 + 종성;
}

bool 받침_있는가(코드포인트 cp) {
    if (!한글_음절인가(cp)) return false;
    return ((cp - 한글_음절_시작) % 종성_개수) != 0;
}

/* ===== NFC 정규화 (한글 특화) ===== */

/*
 * 한글 자모(Jamo) → 음절 합성
 *
 * NFD (분해형): ㅎ(U+1112) + ㅏ(U+1161) + ㄴ(U+11AB) = 3개 코드포인트
 * NFC (조합형): 한(U+D55C) = 1개 코드포인트
 *
 * macOS의 파일시스템이 NFD를 사용하므로 이 변환이 필수.
 */

/* Jamo L (초성): U+1100 ~ U+1112 */
static bool 초성자모인가(코드포인트 cp) {
    return cp >= 0x1100 && cp <= 0x1112;
}

/* Jamo V (중성): U+1161 ~ U+1175 */
static bool 중성자모인가(코드포인트 cp) {
    return cp >= 0x1161 && cp <= 0x1175;
}

/* Jamo T (종성): U+11A8 ~ U+11C2 */
static bool 종성자모인가(코드포인트 cp) {
    return cp >= 0x11A8 && cp <= 0x11C2;
}

size_t 한글_nfc_정규화(char *buf, size_t len) {
    /* 임시 버퍼에 코드포인트 배열로 변환 */
    코드포인트 *코드 = NULL;
    size_t 코드수 = 0;
    size_t 용량 = len; /* 최대 코드포인트 수 (바이트 수보다 작음) */

    코드 = (코드포인트 *)스택할당(용량 * sizeof(코드포인트));

    /* UTF-8 → 코드포인트 배열 */
    const char *p = buf;
    const char *끝 = buf + len;
    while (p < 끝 && *p) {
        코드[코드수++] = utf8_디코딩(&p);
    }

    /* 자모 → 음절 합성 */
    size_t 출력수 = 0;
    size_t i = 0;
    while (i < 코드수) {
        if (초성자모인가(코드[i]) && i + 1 < 코드수 && 중성자모인가(코드[i + 1])) {
            int L = 코드[i] - 0x1100;
            int V = 코드[i + 1] - 0x1161;
            int T = 0;

            if (i + 2 < 코드수 && 종성자모인가(코드[i + 2])) {
                T = 코드[i + 2] - 0x11A7; /* 종성 인덱스 (1부터 시작) */
                코드[출력수++] = 음절_합성(L, V, T);
                i += 3;
            } else {
                코드[출력수++] = 음절_합성(L, V, 0);
                i += 2;
            }
        } else {
            코드[출력수++] = 코드[i++];
        }
    }

    /* 코드포인트 배열 → UTF-8 */
    char *dst = buf;
    for (size_t j = 0; j < 출력수; j++) {
        dst += utf8_인코딩(코드[j], dst);
    }
    *dst = '\0';

    return (size_t)(dst - buf);
}
