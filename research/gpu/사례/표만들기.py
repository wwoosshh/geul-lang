#!/usr/bin/env python3
"""0단계 결과 표를 만든다: 모은 버그(모음/*.json)와 분류(분류.json)를 합쳐 결과.md 를 쓴다.

  python research/gpu/사례/표만들기.py

모음/<출처>.json 은 모으기 단계의 기록(본 후보마다 하나, 포함·제외)이고, 분류.json 은 포함된 버그마다
{url: {갈래, 부갈래, 세부, 판정, 근거, 증상분류}} 이다. 판정 비율은 README 의 방법대로 (거부 + 자리 없음) ÷ 포함 전체.
"""
import collections
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
SOURCES = [("anthropic", "Anthropic 사후 분석"), ("pytorch", "PyTorch"), ("vllm", "vLLM"),
           ("llamacpp", "llama.cpp"), ("flashattn", "FlashAttention")]
VERDICTS = ["거부", "자리 없음", "계약", "조건부", "통과"]
COUNTED = {"거부", "자리 없음"}


def cell(s):
    return str(s or "").replace("|", "\\|").replace("\n", " ")


def main():
    cls = json.load(open(os.path.join(HERE, "분류.json"), encoding="utf-8"))
    out = ["# 0단계 결과 — 표 (표만들기.py 가 만든다, 손으로 고치지 않는다)", ""]
    included = []
    walk = []
    for key, name in SOURCES:
        rows = json.load(open(os.path.join(HERE, "모음", key + ".json"), encoding="utf-8"))
        inc = [r for r in rows if r["결정"] == "포함"]
        exc = [r for r in rows if r["결정"] != "포함"]
        walk.append((name, len(rows), len(inc), len(exc)))
        for r in inc:
            c = cls.get(r["url"] if key != "anthropic" else f'{r["url"]}#{r["번호"]}')
            if c is None:
                raise SystemExit(f"분류가 없다: {name} {r['url']} {r['제목']}")
            included.append((name, r, c))
        out += [f"## {name} — 본 후보 {len(rows)}, 포함 {len(inc)}, 제외 {len(exc)}", "",
                "| 버그 | 증상 | 원인 | 갈래 | 판정 (근거) |", "|---|---|---|---|---|"]
        for r in inc:
            c = cls[r["url"] if key != "anthropic" else f'{r["url"]}#{r["번호"]}']
            sub = f' / {c["부갈래"]}' if c.get("부갈래") else ""
            out.append(f'| [{cell(r["제목"])}]({r["url"]}) | {cell(r["증상"])} | {cell(r["원인"])} | '
                       f'{c["갈래"]}{sub} — {cell(c.get("세부"))} | **{c["판정"]}** — {cell(c.get("근거"))} |')
        if exc:
            out += ["", "<details><summary>제외한 후보</summary>", "", "| 후보 | 제외 이유 |", "|---|---|"]
            for r in exc:
                out.append(f'| [{cell(r["제목"])}]({r["url"]}) | {cell(r["제외_이유"])} |')
            out += ["", "</details>"]
        out.append("")

    n = len(included)
    verdict = collections.Counter(c["판정"] for _, _, c in included)
    branch = collections.Counter(c["갈래"] for _, _, c in included)
    cross = collections.Counter((c["갈래"], c["판정"]) for _, _, c in included)
    symptom = collections.Counter(c["증상분류"] for _, _, c in included)
    counted = sum(verdict[v] for v in COUNTED)
    summary = ["## 요약", "",
               f"포함된 버그 {n}개. 판정에 세는 것(거부 + 자리 없음) **{counted}개 = {counted / n:.0%}** "
               f"(기준: 50% 이상이면 계속).", "",
               "| 판정 | 수 |", "|---|---|"] + [f"| {v} | {verdict[v]} |" for v in VERDICTS] + [""]
    summary += ["| 갈래 | 수 | " + " | ".join(VERDICTS) + " |", "|---|---|" + "---|" * len(VERDICTS)]
    for b, k in branch.most_common():
        summary.append(f"| {b} | {k} | " + " | ".join(str(cross[(b, v)] or "") for v in VERDICTS) + " |")
    summary += ["", "| 증상 | 수 |", "|---|---|"] + [f"| {s} | {k} |" for s, k in symptom.most_common()] + [""]
    summary += ["| 출처 | 본 후보 | 포함 | 제외 |", "|---|---|---|---|"] + \
               [f"| {a} | {b} | {c} | {d} |" for a, b, c, d in walk] + [""]
    text = "\n".join(out[:2] + summary + out[2:]) + "\n"
    open(os.path.join(HERE, "결과.md"), "w", encoding="utf-8", newline="\n").write(text)
    print(f"포함 {n}, 셈 {counted} ({counted / n:.0%}) → 결과.md")


if __name__ == "__main__":
    main()
