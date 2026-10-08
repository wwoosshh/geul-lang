#!/usr/bin/env python3
"""종이 시험의 표기량을 잰다: 커널/ 의 .cu 와 .가상.gl 짝마다 토큰 수와 글자 수 (주석·#include·빈 줄 제외).

  python research/gpu/종이시험/재기.py

토큰은 거칠게 센다 — C 는 식별자·숫자·연산자, 글은 낱말(조사가 붙은 채)·기호. 두 언어의 토큰은 같은 단위가
아니므로 글자 수도 함께 본다. 어느 쪽도 "읽기 쉬움"의 척도는 아니다.
"""
import glob
import io
import os
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))

C_TOK = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|\d+(?:\.\d+)?f?|==|!=|<=|>=|&&|\|\||\+\+|\+=|->|<<|>>|[^\sA-Za-z0-9_]")
G_TOK = re.compile(r"[가-힣A-Za-z0-9_]+|[^\s가-힣A-Za-z0-9_]")


def strip_c(src):
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return "\n".join(l.split("//")[0] for l in src.splitlines() if not l.strip().startswith("#"))


def strip_g(src):
    while "(*" in src:          # 겹친 주석도 안쪽부터 지운다
        src = re.sub(r"\(\*(?:(?!\(\*).)*?\*\)", "", src, flags=re.S)
    return src


def measure(text, tok):
    code = [l for l in text.splitlines() if l.strip()]
    return len(tok.findall(text)), len(re.sub(r"\s", "", text)), len(code)


rows = []
for cu in sorted(glob.glob(os.path.join(HERE, "커널", "*.cu"))):
    name = os.path.basename(cu)[:-3]
    gl = os.path.join(HERE, "커널", name + ".가상.gl")
    c = measure(strip_c(open(cu, encoding="utf-8").read()), C_TOK)
    g = measure(strip_g(open(gl, encoding="utf-8").read()), G_TOK)
    rows.append((name, c, g))

print(f"{'커널':<14} {'CUDA 토큰':>9} {'글 토큰':>7} {'CUDA 글자':>9} {'글 글자':>7} {'CUDA 줄':>7} {'글 줄':>5}")
tot_c = [0, 0, 0]
tot_g = [0, 0, 0]
for name, c, g in rows:
    print(f"{name:<14} {c[0]:>9} {g[0]:>7} {c[1]:>9} {g[1]:>7} {c[2]:>7} {g[2]:>5}")
    for k in range(3):
        tot_c[k] += c[k]
        tot_g[k] += g[k]
print(f"{'합':<14} {tot_c[0]:>9} {tot_g[0]:>7} {tot_c[1]:>9} {tot_g[1]:>7} {tot_c[2]:>7} {tot_g[2]:>5}")
print(f"글/CUDA 비율: 토큰 {tot_g[0] / tot_c[0]:.2f}, 글자 {tot_g[1] / tot_c[1]:.2f}, 줄 {tot_g[2] / tot_c[2]:.2f}")
