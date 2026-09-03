# -*- coding: utf-8 -*-
"""1세대 .글 소스를 2세대 문법으로 기계 변환 (1차). 잔여분은 컴파일러 오류로 잡는다."""
import re, sys, os

TYPES = r"(?:부호없는 )?(?:정수|긴정수|중간정수|짧은정수|작은정수|실수|짧은실수|문자|문자열|참거짓|공허)(?: 참조)*(?:\[\d+\])?"
CINT_FUNCS = {"feof", "putchar", "getchar", "rand", "system", "strncmp", "fclose", "fputs", "fputc", "fgetc", "fseek", "printf", "puts"}
RENAME = {
    "strncmp(": "문자열_일부비교(", "system(": "명령_실행(", "putchar(": "글자쓰기(", "getchar(": "글자받기(",
    "rand(": "난수(", "srand(": "난수씨앗(", "feof(": "파일_끝인가(", "strlen(": "글자수(", "strcmp(": "문자열_비교(",
    "strcpy(": "문자열_복사(", "strcat(": "문자열_연결(", "memcpy(": "메모리_복사(", "malloc(": "할당(", "free(": "해제(",
    "printf(": "쓰기(", "puts(": "쓰기_줄(", "atoi(": "정수로_변환(", "fgets(": "줄_읽기(", "fputs(": "파일_글넣기(",
    "fopen(": "파일_열기(", "fclose(": "파일_닫기(",
}


def convert(text):
    out = []
    for line in text.split("\n"):
        s = line.rstrip("\r")
        # 포함
        if re.match(r'^\s*포함\s+"std(/core)?\.gl"\.?\s*$', s):
            out.append('포함 "표준/입출력.gl"')
            out.append('포함 "표준/문자열.gl"')
            out.append('포함 "표준/체계.gl"')
            continue
        # 외부 선언: 표준 라이브러리가 제공하는 C 함수는 삭제
        m = re.match(r'^\s*외부\s+\[.*\b(feof|putchar|getchar|rand|srand|system|strncmp|strlen|strcmp|printf)\]', s)
        if m:
            out.append(f"(* 1세대 외부 선언 제거: {m.group(1)} — 표준 라이브러리 사용 *)")
            continue
        # 이름은/는 초기화 → =  (블록 헤더 '[...]는 {' 는 제외)
        m = re.match(r'^(\s*)(상수 |정적 )?(' + TYPES + r'|[가-힣A-Za-z_][가-힣A-Za-z_0-9]*)\s+([가-힣A-Za-z_][가-힣A-Za-z_0-9]*)([은는])\s+(.+)\.\s*$', s)
        if m and not s.lstrip().startswith("[") and "{" not in s:
            indent, mod, ty, name, _, rhs = m.groups()
            if re.search(r"(다|하고|해서)\s*$", rhs) and not rhs.startswith("("):
                rhs = "(" + rhs + ")"
            elif re.search(r"[가-힣]다\)?$", rhs) and rhs.startswith("(") and not rhs.endswith(")"):
                rhs = "(" + rhs + ")"
            s = f"{indent}{mod or ''}{ty} {name} = {rhs}."
        # 정의 이름 값. → 상수
        m = re.match(r'^\s*정의\s+([가-힣A-Za-z_][가-힣A-Za-z_0-9]*)\s+(.+)\.\s*$', s)
        if m:
            name, val = m.groups()
            ty = "문자열" if val.startswith('"') else ("실수" if re.match(r'^-?\d+\.\d+$', val) else "정수")
            s = f"상수 {ty} {name} = {val}."
        # 대입의 우변이 SOV 문이면 괄호로 감싼다:  x = a를 f하다.  →  x = (a를 f하다).
        m = re.match(r'^(\s*)([^=<>!"]+?) = ([^=]*[가-힣]다)\.\s*$', s)
        if m and not m.group(3).startswith("(") and "(*" not in s:
            s = f"{m.group(1)}{m.group(2)} = ({m.group(3)})."
        # ++ / -- (문장 어디서든, '다' 어미 허용)
        s = re.sub(r'([가-힣A-Za-z_][가-힣A-Za-z_0-9\[\]]*)\+\+(다)?\.', r'\1를 증가하다.', s)
        s = re.sub(r'([가-힣A-Za-z_][가-힣A-Za-z_0-9\[\]]*)--(다)?\.', r'\1를 감소하다.', s)
        s = re.sub(r':\s*\+\+([^\s)]+)\)', r': \1 += 1)', s)          # for 단계 ++i
        s = re.sub(r':\s*([^\s)]+)\+\+\)', r': \1 += 1)', s)          # for 단계 i++
        # (A) * (B) > 0이면/동안  → (A 그리고 B)이면
        s = re.sub(r'\(([^()]*)\) \* \(([^()]*)\) > 0(이면|동안)', r'(\1 그리고 \2)\3', s)
        s = re.sub(r'\(([^()]*)\) \+ \(([^()]*)\) > 0(이면|동안)', r'(\1 또는 \2)\3', s)
        # 쓰기 계열이 아닌 호출의 문자열 리터럴 안 중괄호는 글자 그대로 → 이스케이프
        if "쓰다" not in s and "쓰기(" not in s and "버퍼에_쓰기(" not in s and "파일에_쓰기(" not in s:
            def esc(m):
                return m.group(0).replace("{", "\\{").replace("}", "\\}")
            s = re.sub(r'"(?:[^"\\]|\\.)*"', esc, s)
        # C 이름 → 한글 (문자열 리터럴 밖에서만)
        parts = re.split(r'("(?:[^"\\]|\\.)*")', s)
        for idx in range(0, len(parts), 2):
            for a, b in sorted(RENAME.items(), key=lambda kv: -len(kv[0])):
                parts[idx] = re.sub(r'(?<![가-힣A-Za-z_0-9])' + re.escape(a), b, parts[idx])
        s = "".join(parts)
        out.append(s)
    return "\n".join(out)


if __name__ == "__main__":
    src, dst = sys.argv[1], sys.argv[2]
    text = open(src, encoding="utf-8-sig").read()
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    open(dst, "w", encoding="utf-8", newline="\n").write(convert(text))
    print("converted", dst)
