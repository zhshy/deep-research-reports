#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""深度投研报告计算器。

提供报告中六类可复算的计算，避免手算误差：
  decompose    跌幅对数分解（估值贡献 / 盈利贡献占比）
  score        加权判据（双层得分、风险归属占比、剔除测试）
  scenario     三情景（概率加权期望、赔率双口径）
  sensitivity  增速 x PE 敏感性矩阵
  position     档位实际增量（k_T x k_L x k_V 三折扣）
  risk         组合风险贡献与等效单一标的仓位
  implied      给定增速反推市场隐含 PE
  erp          股债模型：ERP、z 值、通道→点位映射、口径归因

用法示例：
  python3 calc.py decompose --p0 4371.99 --pe0 55.145 --p1 2413.63 --pe1 26.908
  python3 calc.py score --file judgments.json
  python3 calc.py scenario --cur 2413.63 --file scenarios.json
  python3 calc.py sensitivity --cur 2413.63 --pe-now 26.91 \
      --growths -0.20,-0.10,0,0.12,0.22 --pes 20,24,26.91,32,39
  python3 calc.py position --incr 2 --kt 0.5 --kl 0.5 --kv 1.0
  python3 calc.py risk --w1 0.12 --s1 0.36 --w2 0.10 --s2 0.39 --rho 0.86
  python3 calc.py implied --cur 2413.63 --pe-now 26.91 --g 0.12
  python3 calc.py erp --pe 13.52 --y10 1.634 --mu 5.68 --sd 1.19 --e 296.51 \
      --alt-pe 12.9 --alt-mu 5.05 --alt-sd 1.05
"""

import argparse
import json
import math
import sys


def _pct(x, nd=2):
    return f"{x * 100:+.{nd}f}%"


def _num(x, nd=2):
    return f"{x:,.{nd}f}"


def _table(headers, rows, aligns=None):
    """轻量表格渲染（等宽，中文按 2 字符宽度对齐）。"""
    def width(s):
        return sum(2 if ord(c) > 0x2E7F else 1 for c in str(s))

    cols = len(headers)
    aligns = aligns or ["l"] + ["r"] * (cols - 1)
    data = [list(map(str, headers))] + [[str(c) for c in r] for r in rows]
    w = [max(width(r[i]) for r in data) for i in range(cols)]

    def fmt(r):
        out = []
        for i, cell in enumerate(r):
            pad = w[i] - width(cell)
            out.append(cell + " " * pad if aligns[i] == "l" else " " * pad + cell)
        return "  ".join(out)

    line = fmt(data[0])
    sep = "  ".join("-" * w[i] for i in range(cols))
    body = "\n".join(fmt(r) for r in data[1:])
    return f"{line}\n{sep}\n{body}"


def cmd_decompose(args):
    p0, pe0, p1, pe1 = args.p0, args.pe0, args.p1, args.pe1
    if min(p0, pe0, p1, pe1) <= 0:
        sys.exit("错误：价格与 PE 必须为正数")

    e0, e1 = p0 / pe0, p1 / pe1
    dl_p, dl_e = math.log(p1 / p0), math.log(e1 / e0)
    dl_pe = math.log(pe1 / pe0)

    print(f"隐含 E（起点）= {p0} / {pe0} = {_num(e0, 4)}")
    print(f"隐含 E（终点）= {p1} / {pe1} = {_num(e1, 4)}")
    print(f"对数校验：dlnE + dlnPE = {dl_e + dl_pe:+.6f} ， dlnP = {dl_p:+.6f}"
          f" ， 残差 {abs(dl_e + dl_pe - dl_p):.2e}\n")

    rows = [
        ["PE(TTM)", _num(pe0, 3), _num(pe1, 3), _pct(pe1 / pe0 - 1),
         f"{dl_pe:+.4f}", _pct(dl_pe / dl_p, 1)],
        ["隐含 E", _num(e0, 2), _num(e1, 2), _pct(e1 / e0 - 1),
         f"{dl_e:+.4f}", _pct(dl_e / dl_p, 1)],
        ["点位", _num(p0, 2), _num(p1, 2), _pct(p1 / p0 - 1),
         f"{dl_p:+.4f}", "100.0%"],
    ]
    print(_table(["分解项", "起点", "终点", "变动幅度", "对数贡献", "占总变动比重"], rows))

    pe_share = dl_pe / dl_p
    verdict = ("纯估值杀（估值贡献 >100%，盈利为正向抵减）" if pe_share > 1
               else "估值与盈利同向拖累（混合杀）" if pe_share > 0
               else "纯盈利杀")
    print(f"\n判定：{verdict}")
    print(f"估值压缩贡献 {_pct(pe_share, 1)}，盈利变动贡献 {_pct(dl_e / dl_p, 1)}")
    print("提醒：本分解只证明【已实现层】的干净程度，不能证明未来安全——"
          "分母下修是滞后的，跌幅分解会系统性低估逻辑杀。")


def _load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def cmd_score(args):
    data = _load_json(args.file) if args.file else json.load(sys.stdin)
    if not data:
        sys.exit("错误：判据列表为空")

    total_w = sum(float(j["weight"]) for j in data)
    if abs(total_w - 1.0) > 0.01:
        print(f"警告：权重合计 {total_w:.3f}，不等于 1.0，已自动归一化\n", file=sys.stderr)
    wsum = total_w or 1.0

    rows, total = [], 0.0
    layers = {}
    for i, j in enumerate(data, 1):
        w = float(j["weight"]) / wsum
        s = int(j["score"])
        if s not in (-1, 0, 1):
            sys.exit(f"错误：判据 {i} 的打分必须为 +1/0/-1，当前 {s}")
        contrib = s * w
        total += contrib
        layer = j.get("layer", "-")
        layers.setdefault(layer, 0.0)
        layers[layer] += contrib
        rows.append([i, j.get("name", ""), j.get("value", ""), f"{s:+d}",
                     f"{w * 100:.0f}%", f"{contrib:+.3f}"])

    rows.append(["-", "合计", "-", "-", "100%", f"{total:+.3f}"])
    print(_table(["#", "判据", "观测值", "打分", "权重", "加权得分"], rows))
    print(f"\n加权总分 = {total:+.3f}    风险强度（绝对值）= {abs(total) * 100:.1f}%")
    print("说明：这是【强度】不是【概率】，用途是把'感觉偏空'转化为可比较的量。")

    if layers and len(layers) > 1:
        print("\n分层得分：")
        for k, v in layers.items():
            print(f"  {k}: {v:+.3f}")

    losses = [(j.get("name", f"#{i}"), abs(int(j["score"]) * float(j["weight"]) / wsum))
              for i, j in enumerate(data, 1) if int(j["score"]) < 0]
    total_loss = sum(v for _, v in losses)
    if total_loss > 0:
        print("\n风险归属分解（失分占比）：")
        for name, v in sorted(losses, key=lambda x: -x[1]):
            print(f"  {name}: {v:.3f}  ({v / total_loss * 100:.0f}%)")

        top = max(losses, key=lambda x: x[1])
        # 剔除测试：去掉最大失分项后重算
        drop_idx = next(i for i, j in enumerate(data)
                        if j.get("name", f"#{i+1}") == top[0] and int(j["score"]) < 0)
        rest_total = sum(int(j["score"]) * float(j["weight"]) / wsum
                         for i, j in enumerate(data) if i != drop_idx)
        print(f"\n剔除测试：去掉最大失分项「{top[0]}」后，加权总分 = {rest_total:+.3f}")
        shape = "单点矛盾（问题集中在一处）" if abs(rest_total) < 0.15 else "全面偏空/偏多"
        print(f"判读：{shape}")
        print(f"若为单点矛盾，框架的硬约束应绑定在「{top[0]}」对应的逻辑条件上。")


def cmd_scenario(args):
    data = _load_json(args.file) if args.file else json.load(sys.stdin)
    cur = args.cur
    probs = sum(float(s["prob"]) for s in data)
    if abs(probs - 1.0) > 0.01:
        print(f"警告：概率合计 {probs:.3f}，不等于 1.0", file=sys.stderr)

    rows, expect = [], 0.0
    for s in data:
        central = float(s["central"])
        p = float(s["prob"])
        expect += p * central
        pe_hint = ""
        if args.pe_now:
            e_now = cur / args.pe_now
            g = float(s["g"]) if s.get("g") is not None else 0.0
            pe_hint = f"~{central / (e_now * (1 + g)):.0f}" if g else f"~{central / e_now:.0f}"
        rows.append([s.get("name", ""), f"{p * 100:.0f}%",
                     _num(s.get("pess", central)), _num(central),
                     _num(s.get("opt", central)),
                     _pct(central / cur - 1), pe_hint])
    headers = ["情景", "概率", "悲观", "中枢", "乐观", "中枢相对当前", "中枢隐含 PE"]
    print(_table(headers, rows))
    if args.pe_now:
        has_g = any(s.get("g") is not None for s in data)
        note = ("隐含 PE 按各情景自身增速折算至前瞻盈利口径" if has_g
                else "隐含 PE 沿用当前盈利口径；若在 JSON 中给各情景加 \"g\" 字段，将折算至前瞻盈利口径")
        print(f"注：{note}")

    print(f"\n概率加权期望 = {_num(expect)}  ({_pct(expect / cur - 1)})")

    first, last = data[0], data[-1]
    up = float(first["central"]) - cur
    dn = cur - float(last["central"])
    if dn > 0:
        print(f"赔率（中枢口径）= {up:,.2f} / {dn:,.2f} = {up / dn:.2f} : 1")
    up_t = float(first.get("opt", first["central"])) - cur
    dn_t = cur - float(last.get("pess", last["central"]))
    if dn_t > 0:
        print(f"赔率（尾部口径）= {up_t:,.2f} / {dn_t:,.2f} = {up_t / dn_t:.2f} : 1")
        print("差异说明：中枢口径回答'期望上下空间比'，尾部口径回答'极端情形盈亏比'。"
              "前者好看，后者诚实。")

    if args.pe_now:
        print(f"\n隐含预期反推：若 PE 维持 {args.pe_now} 倍不变，当前点位隐含的盈利增速为 "
              f"{_pct(cur / cur - 1, 1)}（零增长）。")
        print("将其与三情景增速区间对比，增速区间覆盖 0% 的那个情景，就是市场正在定价的情景。")


def cmd_sensitivity(args):
    cur, pe_now = args.cur, args.pe_now
    growths = [float(x) for x in args.growths.split(",")]
    pes = [float(x) for x in args.pes.split(",")]

    headers = ["增速 \\ PE"] + [f"{p:g} 倍" for p in pes]
    rows = []
    for g in growths:
        row = [_pct(g, 0)]
        for p in pes:
            pt = cur * (1 + g) * (p / pe_now)
            row.append(f"{pt:,.0f} ({_pct(pt / cur - 1)})")
        rows.append(row)
    print(_table(headers, rows))
    print(f"\n锚点校验：0% 增速 × {pe_now:g} 倍 应等于当前点位 {cur:,.2f}")

    hi = [cur * (1 + g) * (p / pe_now) for g in growths for p in pes]
    lo = min(hi)
    print(f"矩阵最低点位 {lo:,.0f}（{_pct(lo / cur - 1)}），最高 {max(hi):,.0f}（{_pct(max(hi) / cur - 1)}）")
    print("须从矩阵读出：①价格缓冲来自哪一格 ②真正的尾部在哪一格 ③'不上不下'情形下的合理回报")


def cmd_position(args):
    incr, kt, kl, kv = args.incr, args.kt, args.kl, args.kv
    if kt > 1 or kl > 1 or kv > 1:
        print("提示：折扣系数 >1 视为技术确认加分，上限 1.0", file=sys.stderr)
        kt, kl, kv = min(kt, 1.0), min(kl, 1.0), min(kv, 1.0)
    actual = incr * kt * kl * kv
    print(f"标称增量 {incr:g}% × k_T {kt:g} × k_L {kl:g} × k_V {kv:g} = 实际可执行 {actual:.2f}%")
    print(f"冻结待释放 {incr - actual:.2f}%（待折扣条件改善后补足）")
    if actual < 0.5:
        print("提示：实际增量 < 0.5%，属试探性仓位，应说明'为何仍值得动手'")


def cmd_risk(args):
    w1, s1, w2, s2, rho = args.w1, args.s1, args.w2, args.s2, args.rho
    var = (w1 * s1) ** 2 + (w2 * s2) ** 2 + 2 * w1 * w2 * s1 * s2 * rho
    sp = math.sqrt(var)
    print(f"组合年化风险 = sqrt(({w1}x{s1})^2 + ({w2}x{s2})^2 + 2x{w1}x{w2}x{s1}x{s2}x{rho})")
    print(f"              = {sp * 100:.2f}%")
    print(f"合计名义仓位 = {w1 * 100:.0f}% + {w2 * 100:.0f}% = {(w1 + w2) * 100:.0f}%")
    print(f"等效单一标的仓位（相对标的一）= {sp / s1 * 100:.1f}%")
    print("\n该等效仓位即为组合硬上限的依据：超过它，名义分散失效。")


def cmd_implied(args):
    cur, pe_now, g = args.cur, args.pe_now, args.g
    pe_req = pe_now / (1 + g)
    print(f"若当前点位 {cur:,.2f} 是合理的，且盈利增速为 {_pct(g, 1)}，")
    print(f"则市场隐含的 PE 为 {pe_now:g} / (1 + {g:g}) = {pe_req:.2f} 倍")
    print(f"对比当前 PE {pe_now:g} 倍：{'市场在定价估值下移（de-rating）' if pe_req < pe_now else '市场在定价估值扩张'}"
          f"，差异 {_pct(pe_req / pe_now - 1)}")


def _norm_cdf(z):
    """标准正态 CDF，用于把 z 值翻成分位。"""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def cmd_erp(args):
    pe, y10, mu, sd = args.pe, args.y10, args.mu, args.sd
    if pe <= 0:
        sys.exit("错误：PE 必须为正数")
    if sd <= 0:
        sys.exit("错误：σ 必须为正数")

    if args.e is not None:
        e = args.e
    elif args.level is not None:
        e = args.level / pe
    else:
        sys.exit("错误：需给 --e（隐含盈利）或 --level（当前点位，E = level / PE）")

    ey = 100.0 / pe
    erp = ey - y10
    z = (erp - mu) / sd
    cur = e * pe

    print(f"盈利收益率 = 100 / {pe:g} = {ey:.2f}%")
    print(f"ERP = {ey:.2f}% − {y10:g}% = {erp:.2f}%")
    print(f"z = ({erp:.2f} − {mu:g}) / {sd:g} = {z:+.2f}σ")
    print(f"自身分布分位（正态近似）= {_norm_cdf(z) * 100:.1f}%")
    if abs(z) <= 0.5:
        print("提示：z 落在 ±0.5σ 临界区，不得单独作为决策依据——"
              "须做口径归因（本命令的 --alt-* 参数）并与其他参照系交叉验证。")

    print("\n通道 → 点位映射（E = %.2f，y10 = %g%% 固定）" % (e, y10))
    rows = []
    for k in (2.0, 1.5, 1.0, 0.0, -1.0, -2.0):
        erp_t = mu + k * sd
        pe_t = 100.0 / (erp_t + y10)
        pt = e * pe_t
        label = "μ" if k == 0 else f"{k:+g}σ"
        rows.append([label, f"{erp_t:.2f}%", f"{pe_t:.2f}", f"{pt:,.0f}",
                     _pct(pt / cur - 1), f"{z - k:+.2f}σ"])
    print(_table(["通道", "ERP", "隐含 PE", "点位", "相对当前", "当前距该档"], rows))
    print("读法：μ 那一行是公允价值点位。若它与当前价只差 1%–2%，"
          "说明当前就在公允位置，不是买点。")
    print("注意：E 每变动 1%，整条曲线同向平移 1%——买点是随盈利增长的移动靶。")
    print("注意：σ 变化 0.1，+1σ 买点会移动百点级；点位精度只能到百点，不可当靶心。")

    if args.alt_pe is not None or args.alt_mu is not None or args.alt_sd is not None:
        ape = args.alt_pe if args.alt_pe is not None else pe
        amu = args.alt_mu if args.alt_mu is not None else mu
        asd = args.alt_sd if args.alt_sd is not None else sd
        aey = 100.0 / ape
        aerp = aey - y10
        z0 = (aerp - amu) / asd
        z1 = (erp - amu) / asd     # 先换 PE
        z2 = (erp - mu) / asd      # 再换 μ
        z3 = z                     # 最后换 σ
        print("\n口径归因（宽松口径 → 严格口径，逐项替换，顺序 PE → μ → σ）")
        rows = [
            ["PE", f"{ape:g} → {pe:g}", f"ERP {aerp:.2f}% → {erp:.2f}%", f"{z1 - z0:+.2f}σ"],
            ["μ", f"{amu:g} → {mu:g}", f"均值上移 {mu - amu:+.2f}pp", f"{z2 - z1:+.2f}σ"],
            ["σ", f"{asd:g} → {sd:g}", f"离散度 {sd - asd:+.2f}pp", f"{z3 - z2:+.2f}σ"],
            ["合计", f"z {z0:+.2f}σ → {z3:+.2f}σ", "—", f"{z3 - z0:+.2f}σ"],
        ]
        print(_table(["替换项", "取值", "说明", "对 z 的贡献"], rows))
        print("校验：三项之和应等于合计（逐项替换，无交叉项）。")
        print("结论模板：'ERP 已触及极端低估'这个判断，需要三个选择同时取最宽松的组合才成立；"
              "换成可复算口径，它可能只是回到中枢。")


def _normalize_argv(argv):
    """把 `--opt -0.20,-0.10` 这种以负号开头的取值改写成 `--opt=-0.20,-0.10`，
    否则 argparse 会把它当成新的选项。"""
    value_opts = {"--growths", "--pes"}
    out, i = [], 0
    while i < len(argv):
        if argv[i] in value_opts and i + 1 < len(argv) and argv[i + 1].startswith("-"):
            out.append(f"{argv[i]}={argv[i + 1]}")
            i += 2
        else:
            out.append(argv[i])
            i += 1
    return out


def main():
    ap = argparse.ArgumentParser(description="深度投研报告计算器",
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("decompose", help="跌幅对数分解")
    d.add_argument("--p0", type=float, required=True, help="起点点位")
    d.add_argument("--pe0", type=float, required=True, help="起点 PE")
    d.add_argument("--p1", type=float, required=True, help="终点点位")
    d.add_argument("--pe1", type=float, required=True, help="终点 PE")
    d.set_defaults(func=cmd_decompose)

    s = sub.add_parser("score", help="加权判据")
    s.add_argument("--file", help="JSON 文件；缺省从 stdin 读取")
    s.set_defaults(func=cmd_score)

    sc = sub.add_parser("scenario", help="三情景与赔率")
    sc.add_argument("--cur", type=float, required=True, help="当前点位")
    sc.add_argument("--pe-now", type=float, help="当前 PE，用于估算各情景隐含 PE")
    sc.add_argument("--file", help="JSON 文件；缺省从 stdin 读取")
    sc.set_defaults(func=cmd_scenario)

    se = sub.add_parser("sensitivity", help="敏感性矩阵")
    se.add_argument("--cur", type=float, required=True)
    se.add_argument("--pe-now", type=float, required=True)
    se.add_argument("--growths", required=True, help="逗号分隔，如 -0.2,-0.1,0,0.12,0.22")
    se.add_argument("--pes", required=True, help="逗号分隔，如 20,24,26.91,32,39")
    se.set_defaults(func=cmd_sensitivity)

    p = sub.add_parser("position", help="档位实际增量")
    p.add_argument("--incr", type=float, required=True, help="单档标称增量（百分点）")
    p.add_argument("--kt", type=float, default=0.5, help="时间折扣")
    p.add_argument("--kl", type=float, default=0.5, help="逻辑折扣")
    p.add_argument("--kv", type=float, default=1.0, help="估值折扣")
    p.set_defaults(func=cmd_position)

    r = sub.add_parser("risk", help="组合风险贡献")
    r.add_argument("--w1", type=float, required=True)
    r.add_argument("--s1", type=float, required=True)
    r.add_argument("--w2", type=float, required=True)
    r.add_argument("--s2", type=float, required=True)
    r.add_argument("--rho", type=float, required=True)
    r.set_defaults(func=cmd_risk)

    im = sub.add_parser("implied", help="反推隐含 PE")
    im.add_argument("--cur", type=float, required=True)
    im.add_argument("--pe-now", type=float, required=True)
    im.add_argument("--g", type=float, required=True, help="假设盈利增速，如 0.12")
    im.set_defaults(func=cmd_implied)

    ep = sub.add_parser("erp", help="股债模型（ERP 通道）")
    ep.add_argument("--pe", type=float, required=True, help="当前 PE(TTM)")
    ep.add_argument("--y10", type=float, required=True, help="10Y 国债收益率（百分点），如 1.634")
    ep.add_argument("--mu", type=float, required=True, help="ERP 均值（百分点，实测滚动窗口），如 5.68")
    ep.add_argument("--sd", type=float, required=True, help="ERP 标准差（百分点），如 1.19")
    ep.add_argument("--e", type=float, help="隐含盈利 E（点位 / PE）")
    ep.add_argument("--level", type=float, help="当前点位；与 --e 二选一，E = level / PE")
    ep.add_argument("--alt-pe", type=float, help="口径归因：宽松口径的 PE")
    ep.add_argument("--alt-mu", type=float, help="口径归因：宽松口径的 μ")
    ep.add_argument("--alt-sd", type=float, help="口径归因：宽松口径的 σ")
    ep.set_defaults(func=cmd_erp)

    args = ap.parse_args(_normalize_argv(sys.argv[1:]))
    args.func(args)


if __name__ == "__main__":
    main()
