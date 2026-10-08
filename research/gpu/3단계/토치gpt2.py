#!/usr/bin/env python3
"""3단계의 비교 대상 — 같은 GPT-2 small 을 PyTorch eager 로 (fp32, 그리고 참값용 fp64).

HuggingFace transformers 의 GPT-2 와 같은 연산을 같은 순서로 부른다: Conv1D = torch.addmm(치우침, x, W),
F.layer_norm, F.scaled_dot_product_attention, F.gelu(approximate="tanh"). transformers 는 이 PC 에 없어서 쓰지 않았다 —
이 판은 그보다 군더더기가 적다(파이썬 쪽 일이 적다). KV 캐시는 미리 잡아 둔 텐서에 써 넣는다.
"""
import torch
import torch.nn.functional as F

D, NH, NL, V = 768, 12, 12, 50257


class 토치GPT2:
    def __init__(self, weights, device="cuda", dtype=torch.float32, 최대문장=3, 최대길이=1024):
        t = lambda a: torch.from_numpy(a.copy()).to(device=device, dtype=dtype)
        self.w = {k: t(v) for k, v in weights.items()}
        self.dev, self.dtype = torch.device(device), dtype
        self.kc = torch.zeros(NL, 최대문장, NH, 최대길이, 64, device=device, dtype=dtype)
        self.vc = torch.zeros_like(self.kc)

    @torch.no_grad()
    def 계산(self, tokens, 위치시작, 끝만=False):
        """tokens: [B, m] (long, 같은 장치). 반환: 로짓 [B, m, V] 또는 끝만이면 [B, V]."""
        w = self.w
        B, m = tokens.shape
        x = w["wte.weight"][tokens] + w["wpe.weight"][위치시작:위치시작 + m]
        n = 위치시작 + m
        mask = None
        if m > 1 and 위치시작 > 0:
            qpos = torch.arange(위치시작, n, device=self.dev)[:, None]
            mask = torch.arange(n, device=self.dev)[None, :] <= qpos
        for l in range(NL):
            p = f"h.{l}."
            h = F.layer_norm(x, (D,), w[p + "ln_1.weight"], w[p + "ln_1.bias"], 1e-5)
            qkv = torch.addmm(w[p + "attn.c_attn.bias"], h.view(-1, D), w[p + "attn.c_attn.weight"]).view(B, m, 3 * D)
            q, k, v = qkv.split(D, dim=2)
            q = q.view(B, m, NH, 64).transpose(1, 2)
            self.kc[l, :B, :, 위치시작:n] = k.view(B, m, NH, 64).transpose(1, 2)
            self.vc[l, :B, :, 위치시작:n] = v.view(B, m, NH, 64).transpose(1, 2)
            K, Vv = self.kc[l, :B, :, :n], self.vc[l, :B, :, :n]
            if m == 1:
                y = F.scaled_dot_product_attention(q, K, Vv)
            elif 위치시작 == 0:
                y = F.scaled_dot_product_attention(q, K, Vv, is_causal=True)
            else:
                y = F.scaled_dot_product_attention(q, K, Vv, attn_mask=mask)
            y = y.transpose(1, 2).reshape(B * m, D)
            x = x + torch.addmm(w[p + "attn.c_proj.bias"], y, w[p + "attn.c_proj.weight"]).view(B, m, D)
            h = F.layer_norm(x, (D,), w[p + "ln_2.weight"], w[p + "ln_2.bias"], 1e-5)
            f = F.gelu(torch.addmm(w[p + "mlp.c_fc.bias"], h.view(-1, D), w[p + "mlp.c_fc.weight"]), approximate="tanh")
            x = x + torch.addmm(w[p + "mlp.c_proj.bias"], f, w[p + "mlp.c_proj.weight"]).view(B, m, D)
        if 끝만:
            x = x[:, -1]
        x = F.layer_norm(x, (D,), w["ln_f.weight"], w["ln_f.bias"], 1e-5)
        return F.linear(x, w["wte.weight"])

    @torch.no_grad()
    def 생성(self, ids, n):
        """탐욕 생성(문장 하나). 다음 토큰은 GPU 에서 고르고 호스트는 마지막에 한 번 받는다."""
        t = torch.tensor([ids], device=self.dev)
        nxt = self.계산(t, 0, 끝만=True).argmax(-1, keepdim=True)
        out = [nxt]
        for s in range(n - 1):
            nxt = self.계산(nxt, len(ids) + s, 끝만=True).argmax(-1, keepdim=True)
            out.append(nxt)
        return torch.cat(out, 1)[0].tolist()


class 토치그래프생성:
    """참고용(판정 밖) — 같은 모델의 decode 한 걸음을 CUDA 그래프로 잡아 파이썬·실행 비용을 없앤 판.
    캐시를 정적 길이(최대길이)로 두고 가림으로 위치를 고른다(HF 의 static cache 와 같은 방식)."""

    def __init__(self, model, 최대길이=128):
        self.m, self.n = model, 최대길이
        dev = model.dev
        self.tok = torch.zeros(1, 1, dtype=torch.long, device=dev)
        self.pos = torch.zeros(1, dtype=torch.long, device=dev)
        self.out = torch.zeros(최대길이 + 1, dtype=torch.long, device=dev)
        self.keys = torch.arange(최대길이, device=dev)
        s = torch.cuda.Stream()
        s.wait_stream(torch.cuda.current_stream())
        with torch.cuda.stream(s):
            for _ in range(3):
                self._걸음()
        torch.cuda.current_stream().wait_stream(s)
        self.g = torch.cuda.CUDAGraph()
        with torch.cuda.graph(self.g):
            self._걸음()

    @torch.no_grad()
    def _걸음(self):
        m, w, n = self.m, self.m.w, self.n
        x = w["wte.weight"][self.tok] + w["wpe.weight"].index_select(0, self.pos)
        mask = self.keys <= self.pos
        for l in range(NL):
            p = f"h.{l}."
            h = F.layer_norm(x, (D,), w[p + "ln_1.weight"], w[p + "ln_1.bias"], 1e-5)
            qkv = torch.addmm(w[p + "attn.c_attn.bias"], h.view(-1, D), w[p + "attn.c_attn.weight"]).view(1, 1, 3 * D)
            q, k, v = qkv.split(D, dim=2)
            q = q.view(1, 1, NH, 64).transpose(1, 2)
            kc, vc = m.kc[l, :1, :, :n], m.vc[l, :1, :, :n]
            kc.index_copy_(2, self.pos, k.view(1, 1, NH, 64).transpose(1, 2))
            vc.index_copy_(2, self.pos, v.view(1, 1, NH, 64).transpose(1, 2))
            y = F.scaled_dot_product_attention(q, kc, vc, attn_mask=mask).transpose(1, 2).reshape(1, D)
            x = x + torch.addmm(w[p + "attn.c_proj.bias"], y, w[p + "attn.c_proj.weight"]).view(1, 1, D)
            h = F.layer_norm(x, (D,), w[p + "ln_2.weight"], w[p + "ln_2.bias"], 1e-5)
            f = F.gelu(torch.addmm(w[p + "mlp.c_fc.bias"], h.view(-1, D), w[p + "mlp.c_fc.weight"]), approximate="tanh")
            x = x + torch.addmm(w[p + "mlp.c_proj.bias"], f, w[p + "mlp.c_proj.weight"]).view(1, 1, D)
        x = F.layer_norm(x[:, -1], (D,), w["ln_f.weight"], w["ln_f.bias"], 1e-5)
        nxt = F.linear(x, w["wte.weight"]).argmax(-1, keepdim=True)
        self.out.index_copy_(0, self.pos + 1, nxt.view(1))
        self.tok.copy_(nxt)
        self.pos.add_(1)

    @torch.no_grad()
    def 생성(self, ids, n):
        p = len(ids)
        assert p + n <= self.n
        nxt = self.m.계산(torch.tensor([ids], device=self.m.dev), 0, 끝만=True).argmax(-1, keepdim=True)
        self.tok.copy_(nxt)
        self.pos.fill_(p)
        self.out[p] = nxt[0, 0]
        for _ in range(n - 1):
            self.g.replay()
        return self.out[p:p + n].tolist()
