"""작은 함수 인라인 (D-31). 하강이 끝난 IR 을 한 번 훑어 조건에 맞는 호출을 펼친다.

두 구현이 같은 바이트를 내야 하므로 규칙을 그대로 self/인라인.gl 에 옮긴다:
- 후보: 정의된 비가변 함수, 라벨을 뺀 본문이 12 명령 이하, 점프·분기·호출·가변인자가 없고,
  반환이 끝에만 있으며, 매개변수·반환에 집합체가 없고, 진입 함수가 아니다.
  호출을 허용해 보았으나 감싸는 함수의 호출이 그대로 남아 IR 이 27% 늘고 호출은 2% 만 줄어 기각했다.
- 호출 자리마다 매개변수를 지역으로 만들어 인자를 저장하고, 본문을 복사한 뒤 반환값을 복사한다.
- 한 겹만 편다. 펼친 본문 안의 호출은 더 펴지 않는다 (후보에 호출이 없으므로 애초에 없다).
- 새로 만드는 지역 이름은 `<함수>.<이름>.<번호>` 다. 번호는 호출자마다 1 부터 센다.
"""
from . import types as T
from .ir import Temp
from .sema import VarSym

LIMIT = 12
OPERANDS = {
    "copy": ("src",), "load": ("addr",), "store": ("addr", "src"), "gep": ("base",),
    "index_addr": ("base", "idx"), "bin": ("a", "b"), "cmp": ("a", "b"), "neg": ("a",),
    "not": ("a",), "lnot": ("a",), "cast": ("src",), "ret": ("value",),
}
BODY_OPS = set(OPERANDS) | {"const", "fconst", "str", "addr_local", "addr_global", "func_addr"}


def candidates(mod):
    """인라인할 수 있는 함수: 이름 → IRFunction. 정의 순서를 지킨다."""
    out = {}
    for f in mod.functions:
        if f.is_entry or f.variadic:
            continue
        body = [i for i in f.insts if i.op != "label"]
        if len(body) > LIMIT:
            continue
        if any(i.op not in BODY_OPS for i in body):
            continue
        rets = [k for k, i in enumerate(f.insts) if i.op == "ret"]
        if not rets or min(rets) < len(f.insts) - 2:
            continue
        if any(t.is_agg() for _, t in f.params):
            continue
        if f.ret is not None and f.ret.is_agg():
            continue
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

    # 매개변수: 지역을 만들어 인자를 넣는다
    for (psym, ptype), arg in zip(g.params, i.args):
        addr = f.new_temp(T.PtrType(ptype))
        out.append(("addr_local", dict(dst=addr, var=sym_for(psym))))
        out.append(("store", dict(addr=addr, src=arg, type=ptype)))
    for inst in g.insts:
        op = inst.op
        if op == "label":
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
