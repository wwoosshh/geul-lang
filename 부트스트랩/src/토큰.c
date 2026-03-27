/*
 * 토큰.c - 토큰 유틸리티 함수 구현
 */
#include "토큰.h"

/* 토큰 종류의 한글 이름 */
const char *토큰_이름(토큰_종류 종류) {
    switch (종류) {
    /* 리터럴 */
    case 토큰_정수_리터럴:   return "숫자";
    case 토큰_실수_리터럴:   return "소수";
    case 토큰_문자열_리터럴: return "문자열";
    case 토큰_문자_리터럴:   return "문자";

    /* 식별자 */
    case 토큰_식별자:        return "이름";

    /* 타입 */
    case 토큰_정수:          return "정수";
    case 토큰_긴정수:        return "긴정수";
    case 토큰_짧은정수:      return "짧은정수";
    case 토큰_작은정수:      return "작은정수";
    case 토큰_부호없는:      return "부호없는";
    case 토큰_실수:          return "실수";
    case 토큰_짧은실수:      return "짧은실수";
    case 토큰_문자:          return "문자";
    case 토큰_문자열:        return "문자열";
    case 토큰_참거짓:        return "참거짓";
    case 토큰_공허:          return "공허";

    /* 값 */
    case 토큰_참:            return "참";
    case 토큰_거짓:          return "거짓";
    case 토큰_없음:          return "없음";

    /* 구조 */
    case 토큰_묶음:          return "묶음";
    case 토큰_나열:          return "나열";
    case 토큰_함수:          return "함수";
    case 토큰_반환:          return "반환";
    case 토큰_탈출:          return "탈출";
    case 토큰_계속:          return "계속";
    case 토큰_크기:          return "크기";
    case 토큰_포함:          return "포함";
    case 토큰_정의:          return "정의";
    case 토큰_아니면:        return "아니면";
    case 토큰_참조:          return "참조";
    case 토큰_외부:          return "외부";
    case 토큰_증가:          return "++";
    case 토큰_감소:          return "--";
    case 토큰_더하기대입:    return "+=";
    case 토큰_빼기대입:      return "-=";
    case 토큰_곱하기대입:    return "*=";
    case 토큰_나누기대입:    return "/=";
    case 토큰_나머지대입:    return "%=";
    case 토큰_별칭:          return "별칭";
    case 토큰_반복:          return "반복";
    case 토큰_갈래:          return "갈래";
    case 토큰_경우:          return "경우";
    case 토큰_기본:          return "기본";
    case 토큰_정적:          return "정적";
    case 토큰_상수:          return "상수";
    case 토큰_가변목록:      return "가변목록";
    case 토큰_가변시작:      return "가변시작";
    case 토큰_가변끝:        return "가변끝";
    case 토큰_가변인자:      return "가변인자";
    case 토큰_반복하기:      return "반복하기";
    case 토큰_이동:          return "이동";
    case 토큰_전처리:        return "#";
    case 토큰_만약정의:      return "만약정의";
    case 토큰_만약미정의:    return "만약미정의";
    case 토큰_합침:          return "합침";
    case 토큰_없으면:        return "없으면";
    case 토큰_있으면:        return "있으면";
    case 토큰_정리:          return "정리";
    case 토큰_넘기다:        return "넘기다";

    /* 조사 */
    case 토큰_조사_을:       return "을";
    case 토큰_조사_를:       return "를";
    case 토큰_조사_이:       return "이";
    case 토큰_조사_가:       return "가";
    case 토큰_조사_은:       return "은";
    case 토큰_조사_는:       return "는";
    case 토큰_조사_에:       return "에";
    case 토큰_조사_로:       return "로";
    case 토큰_조사_으로:     return "으로";
    case 토큰_조사_에서:     return "에서";
    case 토큰_조사_부터:     return "부터";
    case 토큰_조사_까지:     return "까지";
    case 토큰_조사_와:       return "와";
    case 토큰_조사_과:       return "과";
    case 토큰_조사_의:       return "의";
    case 토큰_조사_보다:     return "보다";
    case 토큰_조사_에게:     return "에게";

    /* 어미 */
    case 토큰_어미_다:       return "다";
    case 토큰_어미_면:       return "면";
    case 토큰_어미_고:       return "고";
    case 토큰_어미_서:       return "서";
    case 토큰_어미_여:       return "여";
    case 토큰_어미_거나:     return "거나";
    case 토큰_어미_지만:     return "지만";
    case 토큰_어미_도록:     return "도록";
    case 토큰_어미_동안:     return "동안";
    case 토큰_어미_때:       return "때";
    case 토큰_어미_라:       return "라";
    case 토큰_어미_자:       return "자";
    case 토큰_어미_까:       return "까";
    case 토큰_어미_며:       return "며";
    case 토큰_어미_면서:     return "면서";

    /* 구분자 */
    case 토큰_여는괄호:      return "(";
    case 토큰_닫는괄호:      return ")";
    case 토큰_여는중괄호:    return "{";
    case 토큰_닫는중괄호:    return "}";
    case 토큰_여는대괄호:    return "[";
    case 토큰_닫는대괄호:    return "]";
    case 토큰_쉼표:          return ",";
    case 토큰_마침표:        return ".";
    case 토큰_쌍점:          return ":";
    case 토큰_화살표:        return "→";
    case 토큰_물음표:        return "?";

    /* 연산자 */
    case 토큰_더하기:        return "+";
    case 토큰_빼기:          return "-";
    case 토큰_곱하기:        return "*";
    case 토큰_나누기:        return "/";
    case 토큰_나머지:        return "%";
    case 토큰_같다:          return "==";
    case 토큰_다르다:        return "!=";
    case 토큰_크다:          return ">";
    case 토큰_작다:          return "<";
    case 토큰_크거나같다:    return ">=";
    case 토큰_작거나같다:    return "<=";
    case 토큰_그리고:        return "&&";
    case 토큰_또는:          return "||";
    case 토큰_아닌:          return "!";
    case 토큰_비트와:        return "&";
    case 토큰_비트또는:      return "|";
    case 토큰_비트배타:      return "^";
    case 토큰_비트아닌:      return "~";
    case 토큰_왼쪽이동:      return "<<";
    case 토큰_오른쪽이동:    return ">>";
    case 토큰_대입:          return "=";
    case 토큰_주소:          return "&(주소)";

    /* 특수 */
    case 토큰_줄바꿈:        return "줄바꿈";
    case 토큰_파일끝:        return "파일 끝";
    case 토큰_오류:          return "오류";
    }
    return "알수없음";
}

bool 조사_토큰인가(토큰_종류 종류) {
    return 종류 >= 토큰_조사_을 && 종류 <= 토큰_조사_에게;
}

bool 어미_토큰인가(토큰_종류 종류) {
    return 종류 >= 토큰_어미_다 && 종류 <= 토큰_어미_면서;
}

조사_역할 조사_역할_분류(토큰_종류 종류) {
    switch (종류) {
    case 토큰_조사_을:
    case 토큰_조사_를:   return 역할_목적어;
    case 토큰_조사_이:
    case 토큰_조사_가:   return 역할_주어;
    case 토큰_조사_은:
    case 토큰_조사_는:   return 역할_주제;
    case 토큰_조사_에:   return 역할_목적지;
    case 토큰_조사_로:
    case 토큰_조사_으로: return 역할_수단;
    case 토큰_조사_에서: return 역할_출처;
    case 토큰_조사_부터: return 역할_시작;
    case 토큰_조사_까지: return 역할_종점;
    case 토큰_조사_와:
    case 토큰_조사_과:   return 역할_공동;
    case 토큰_조사_의:   return 역할_소유;
    case 토큰_조사_보다: return 역할_비교;
    case 토큰_조사_에게: return 역할_대상;
    default:             return 역할_없음;
    }
}

어미_기능 어미_기능_분류(토큰_종류 종류) {
    switch (종류) {
    case 토큰_어미_다:   return 어미_종결;
    case 토큰_어미_면:   return 어미_조건;
    case 토큰_어미_고:   return 어미_순차;
    case 토큰_어미_서:
    case 토큰_어미_여:   return 어미_파이프;
    case 토큰_어미_거나: return 어미_선택;
    case 토큰_어미_지만: return 어미_양보;
    case 토큰_어미_도록: return 어미_목적;
    case 토큰_어미_동안: return 어미_지속;
    case 토큰_어미_때:   return 어미_시점;
    case 토큰_어미_라:   return 어미_명령;
    case 토큰_어미_자:   return 어미_제안;
    case 토큰_어미_까:   return 어미_의문;
    case 토큰_어미_며:
    case 토큰_어미_면서: return 어미_동시;
    default:             return 어미_없음;
    }
}
