"""透平 vs 螺杆：全年发电量对比（同一额定电功率、同一站场流量曲线）。

思路：
  * 膨胀机与调压器并联，流量超过膨胀机能力的部分走调压器；
    流量低于最小运行流量时停机，全部走调压器。
  * 每小时电功率 = 实际通过膨胀机的质量流量 × 单位质量电功（随部分负荷效率变化）。
  * 单位质量电功由 pressure_letdown_calc 的实际气体模型计算（出口温度控制在 ≥5 °C）。

流量数据：
  * 默认用一条“示意”城市门站流量曲线（冬夏季节变化 + 日内早中晚高峰），仅用于说明规律；
  * 拿到真实数据后用 --csv 读入（单列，每行一个小时流量 Nm³/h，8760 行左右）。

部分负荷效率曲线为行业经验假设（可在下方 CURVES 中修改），结果为方案阶段估算。

用法：
    python tools/annual_compare.py --p1 4.0 --p2 1.6 --pe 300 --mean 12000
    python tools/annual_compare.py --p1 4.0 --p2 1.6 --pe 300 --csv flow.csv
"""

import argparse
import math
import random

from pressure_letdown_calc import Gas, size_case

# 部分负荷曲线：(相对设计流量, 相对设计点效率)，以及设计点等熵效率、最小运行流量比
CURVES = {
    "向心透平(可调喷嘴+变速)": {
        "eta": 0.82,
        "min_flow": 0.35,
        "curve": [(0.35, 0.74), (0.4, 0.80), (0.5, 0.87), (0.6, 0.92), (0.7, 0.96),
                  (0.8, 0.98), (0.9, 0.995), (1.0, 1.0)],
    },
    "双螺杆(变频变速)": {
        "eta": 0.72,
        "min_flow": 0.20,
        "curve": [(0.2, 0.72), (0.3, 0.82), (0.4, 0.89), (0.5, 0.94), (0.6, 0.97),
                  (0.7, 0.99), (0.8, 1.0), (1.0, 1.0)],
    },
}


def interp(points, x):
    if x <= points[0][0]:
        return points[0][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return points[-1][1]


def synthetic_profile(mean, seed=1):
    """示意城市门站逐时流量：1 月最高、7 月最低（峰谷约 2:1），日内早中晚三个高峰。"""
    rnd = random.Random(seed)
    hourly_shape = [0.55, 0.5, 0.48, 0.48, 0.52, 0.65, 0.95, 1.25, 1.30, 1.10, 1.05, 1.20,
                    1.25, 1.05, 0.95, 0.95, 1.05, 1.30, 1.40, 1.30, 1.10, 0.95, 0.80, 0.65]
    flows = []
    for d in range(365):
        season = 1 + 0.35 * math.cos(2 * math.pi * (d - 15) / 365)
        for h in range(24):
            flows.append(season * hourly_shape[h] * rnd.uniform(0.93, 1.07))
    k = mean / (sum(flows) / len(flows))
    return [f * k for f in flows]


def read_csv(path):
    with open(path, encoding="utf-8") as f:
        return [float(line.split(",")[0]) for line in f if line.strip() and line[0].isdigit()]


def evaluate(gas, flows, p1, p2, pe_kw, eta_el, spec):
    eta_d = spec["eta"]
    # 预计算：单位标方电功 kWh/Nm³ 与效率的关系（效率区间内取若干点插值）
    etas = [eta_d * r for r in (0.6, 0.7, 0.8, 0.9, 1.0)]
    table = []
    for e in etas:
        r = size_case(gas, p1, p2, pe_kw, e, eta_el, 5.0, 10.0)
        table.append((e, pe_kw / r["q_n"], r["q_heat"] / r["q_n"]))  # kWh/Nm³ 电、热
    q_design = pe_kw / table[-1][1]

    energy = heat = hours = 0.0
    for q in flows:
        phi = min(q / q_design, 1.0)
        if phi < spec["min_flow"]:
            continue
        e = eta_d * interp(spec["curve"], phi)
        e_kwh = interp([(t[0], t[1]) for t in table], e)
        h_kwh = interp([(t[0], t[2]) for t in table], e)
        q_exp = phi * q_design
        energy += q_exp * e_kwh
        heat += q_exp * h_kwh
        hours += 1
    return q_design, energy / 1e3, heat / 1e3, hours


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--p1", type=float, default=4.0)
    ap.add_argument("--p2", type=float, default=1.6)
    ap.add_argument("--pe", type=float, default=300.0, help="额定上网电功率 kW")
    ap.add_argument("--eta-el", type=float, default=0.92)
    ap.add_argument("--mean", type=float, nargs="+", default=[12000.0], help="示意曲线的年平均流量 Nm³/h，可给多个")
    ap.add_argument("--csv", help="真实逐时流量 CSV（单列 Nm³/h）")
    a = ap.parse_args()

    gas = Gas()
    cases = [("实测数据", read_csv(a.csv))] if a.csv else [
        (f"示意曲线 年均 {m:.0f} Nm³/h", synthetic_profile(m)) for m in a.mean]

    print(f"工况 {a.p1} → {a.p2} MPa(g)，额定电功率 {a.pe:.0f} kW\n")
    for title, flows in cases:
        print(f"== {title}（最小 {min(flows):.0f}，最大 {max(flows):.0f}）==")
        for name, spec in CURVES.items():
            qd, mwh, heat, hrs = evaluate(gas, flows, a.p1, a.p2, a.pe, a.eta_el, spec)
            print(f"  {name:<16} 满发需流量 {qd:7.0f} Nm³/h | 年发电 {mwh:7.0f} MWh | "
                  f"运行 {hrs:5.0f} h | 等效满发 {mwh * 1e3 / a.pe:5.0f} h | 预热热量 {heat:6.0f} MWh")
        print()


if __name__ == "__main__":
    main()
