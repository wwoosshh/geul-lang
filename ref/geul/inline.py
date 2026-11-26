"""작은 함수 인라인 (D-31, D-55). 하강이 끝난 IR 을 한 번 훑어 조건에 맞는 호출을 펼친다.

두 구현이 같은 바이트를 내야 하므로 규칙을 그대로 self/하강.gl 에 옮긴다:
- 후보: 정의된 비가변 함수, 반환이 끝에만 있으며, 매개변수·반환에 집합체가 없고, 진입 함수가 아니다. 그리고 둘 중 하나:
  (1) 라벨을 뺀 본문이 본문 연산뿐(점프·분기·호출·가변인자 없음)이고 24 명령 이하 (D-31 에서 12, D-56 에서 24 —
      매개변수 둘인 한 줄 함수도 지역주소 · 적재 짝을 세면 12 를 넘었다).
      호출을 허용해 보았으나 감싸는 함수의 호출이 그대로 남아 IR 이 27% 늘고 호출은 2% 만 줄어 기각했다.
  (2) 가드 꼴(D-55): 라벨을 뺀 본문이 본문 연산 · 분기 · 점프 · 호출뿐이고 32 명령 이하, 점프 · 분기가 모두 앞으로 가며(반복이 없다),
      호출은 어떤 분기의 참 쪽 라벨로 시작하는 블록에만 하나씩 있다 — 범위 검사 뒤에 원소를 읽는 접근 함수(정수목록_값 같은)의 꼴.
      감싸는 함수는 그 호출이 가드 밖에 있어 여전히 후보가 아니다.
- 호출 자리마다 매개변수를 지역으로 만들어 인자를 저장하고, 본문을 복사한 뒤 반환값을 복사한다. 가드 꼴은 라벨을 호출자의 새
  라벨(`.<호출자>.인라인<번호>`)로 바꾸는데, 처음 만나는 차례(분기는 참 쪽 · 거짓 쪽 차례)로 만든다.
- 한 겹만 편다. 펼친 본문 안의 호출(가드 안의 것)은 더 펴지 않는다. 다만 함수를 차례로 고쳐 쓰므로, 앞서 고친 후보를 뒤에서 펴면
  고친 본문이 들어간다 — 두 구현이 같은 차례로 한다.
- 새로 만드는 지역 이름은 `<함수>.<이름>.<번호>` 다. 번호는 호출자마다 1 부터 센다.
"""
from . import types as T
from .ir import Temp
from .sema import VarSym

LIMIT = 24                 # 곧은 함수(1)의 본문 한도 — 라벨을 뺀 명령 수 (D-56)
LIMIT_GUARD = 32           # 가드 꼴(D-55)의 본문 한도 — 라벨을 뺀 명령 수
OPERANDS = {
    "copy": ("src",), "load": ("addr",), "store": ("addr", "src"), "gep": ("base",),
    "index_addr": ("base", "idx"), "bin": ("a", "b"), "cmp": ("a", "b"), "neg": ("a",),
    "not": ("a",), "lnot": ("a",), "cast": ("src",), "ret": ("value",), "br": ("cond",),
}
BODY_OPS = set(OPERANDS) - {"br"} | {"const", "fconst", "str", "addr_local", "addr_global", "func_addr"}
GUARD_OPS = BODY_OPS | {"br", "jmp", "call"}


def guarded(f):
    """가드 꼴 (D-55): 점프 · 분기가 모두 앞으로 가고(반복이 없다), 부름은 어떤 분기의 참 쪽 라벨로 시작하는 블록에만 하나씩 있다.
    `(위치 < 0 또는 위치 >= 길이)이면 { 범위검사(…). }` 뒤에 원소를 읽는 접근 함수의 꼴이다 — 드문 쪽(가드)에만 부름이 있다."""
    pos = {i.name: k for k, i in enumerate(f.insts) if i.op == "label"}
    참쪽 = set()
    for k, i in enumerate(f.insts):
        if i.op == "br":
            if pos.get(i.ltrue, -1) <= k or pos.get(i.lfalse, -1) <= k:
                return False
            참쪽.add(i.ltrue)
        elif i.op == "jmp" and pos.get(i.label, -1) <= k:
            return False
    블록, 부름수 = None, 0
    for i in f.insts:
        if i.op == "label":
            블록, 부름수 = i.name, 0
        elif i.op in ("br", "jmp"):
            블록 = None
        elif i.op == "call":
            if 블록 not in 참쪽 or 부름수:
                return False
            부름수 += 1
    return True


def candidates(mod):
    """인라인할 수 있는 함수: 이름 → IRFunction. 정의 순서를 지킨다."""
    out = {}
    for f in mod.functions:
        if f.is_entry or f.variadic:
            continue
        body = [i for i in f.insts if i.op != "label"]
        rets = [k for k, i in enumerate(f.insts) if i.op == "ret"]
        if not rets or min(rets) < len(f.insts) - 2:
            continue
        if any(t.is_agg() for _, t in f.params):
            continue
        if f.ret is not None and f.ret.is_agg():
            continue
        if all(i.op in BODY_OPS for i in body):
            if len(body) <= LIMIT:
                out[f.name] = f
        elif len(body) <= LIMIT_GUARD and all(i.op in GUARD_OPS for i in body) and guarded(f):
            out[f.name] = f
    return out


def inline_call(f, i, g, counter):
    """호출 i (f 안, 대상 g) 를 펼친 명령 목록을 돌려준다."""
    out = []
    vmap = {}
    tmap = {}

    def sym_for(sym):
        if sym not in vmap:
            counter[0] += 1
            new = VarSym(f"{g.name}.{sym.name}.{counter[0]}", sym.type, "local", sym.pos)
            f.locals.append(new)
            vmap[sym] = new
        return vmap[sym]

    def temp_for(t):
        if t not in tmap:
            tmap[t] = f.new_temp(t.type)
        return tmap[t]

    def val(x):
        return temp_for(x) if isinstance(x, Temp) else x

    # 가드 꼴(D-55)이면 g 의 라벨을 호출자의 새 라벨로 — 처음 만나는 차례대로
    흐름 = any(x.op in ("br", "jmp") for x in g.insts)
    lmap = {}

    def lab(name):
        if name not in lmap:
            lmap[name] = f.new_label("인라인")
        return lmap[name]

    # 매개변수: 지역을 만들어 인자를 넣는다
    for (psym, ptype), arg in zip(g.params, i.args):
        addr = f.new_temp(T.PtrType(ptype))
        out.append(("addr_local", dict(dst=addr, var=sym_for(psym))))
        out.append(("store", dict(addr=addr, src=arg, type=ptype)))
    for inst in g.insts:
        op = inst.op
        if op == "label":
            if 흐름:
                out.append(("label", dict(name=lab(inst.name))))
            continue
        if op == "jmp":
            out.append(("jmp", dict(label=lab(inst.label))))
            continue
        if op == "br":
            out.append(("br", dict(cond=val(inst.cond), ltrue=lab(inst.ltrue), lfalse=lab(inst.lfalse))))
            continue
        if op == "ret":
            if inst.value is not None and i.dst is not None:
                out.append(("copy", dict(dst=i.dst, src=val(inst.value))))
            continue
        kw = {}
        for k, v in inst.__dict__.items():
            if k == "op":
                continue
            if k == "dst":
                kw[k] = temp_for(v) if v is not None else None
            elif k in OPERANDS.get(op, ()):
                kw[k] = val(v)
            elif k == "args":
                kw[k] = [val(a) for a in v]
            elif k == "callee":
                kw[k] = v if isinstance(v, str) else val(v)
            elif k == "var":
                kw[k] = sym_for(v) if op == "addr_local" else v
            else:
                kw[k] = v
        out.append((op, kw))
    return out


def run(mod):
    cands = candidates(mod)
    if not cands:
        return mod
    for f in mod.functions:
        counter = [0]
        new_insts = []
        for i in f.insts:
            g = cands.get(i.callee) if (i.op == "call" and isinstance(i.callee, str) and not i.extern) else None
            if g is None or g is f or len(i.args) != len(g.params):
                new_insts.append(i)
                continue
            f.max_call_args = max(f.max_call_args, g.max_call_args)
            for op, kw in inline_call(f, i, g, counter):
                new_insts.append(_mk(op, kw))
        f.insts = new_insts
    return mod


def _mk(op, kw):
    from .ir import inst
    return inst(op, **kw)
