"""天然气余压（管网压力能）发电 —— 热力估算工具。

用途：给定进出口压力、膨胀机效率和目标电功率，估算
  * 膨胀机进口所需预热温度（保证出口温度不低于设定值，防冻堵/水合物）
  * 所需天然气质量流量与标准体积流量（Nm³/h，0 °C、101.325 kPa）
  * 预热热负荷（从进站温度加热到所需进口温度）
  * 对照：同压降下调压阀节流（焦耳-汤姆逊）后的出口温度

物性采用 CoolProp（HEOS 多参数状态方程，混合规则同 GERG-2008），默认气质为典型管输气。
仅用于方案阶段估算，正式设计请以实测组分 + GERG-2008/AGA8 计算为准。

用法示例：
    python tools/pressure_letdown_calc.py --p1 4.0 --p2 1.6 --pe 300
    python tools/pressure_letdown_calc.py --table
"""

import argparse

import CoolProp.CoolProp as CP

# 典型管输天然气组分（摩尔分数），可按实际气质分析报告修改
DEFAULT_GAS = {
    "Methane": 0.930,
    "Ethane": 0.035,
    "Propane": 0.008,
    "Nitrogen": 0.015,
    "CarbonDioxide": 0.012,
}

P_ATM = 101.325e3  # Pa
T_NORMAL = 273.15  # K，标准状态 0 °C


class Gas:
    def __init__(self, gas=DEFAULT_GAS):
        total = sum(gas.values())
        self.names = list(gas)
        self.fractions = [v / total for v in gas.values()]
        self.state = CP.AbstractState("HEOS", "&".join(self.names))
        self.state.set_mole_fractions(self.fractions)
        # 指定为气相，跳过相稳定性判断（快约 500 倍）；
        # 管输气在本工具涉及的温压范围内均为单相气体，极低出口温度时结果仅供参考
        self.state.specify_phase(CP.iphase_gas)
        self.rho_n = self._prop(T_NORMAL, P_ATM, "rhomass")

    def describe(self):
        return " + ".join(f"{n} {x * 100:.1f}%" for n, x in zip(self.names, self.fractions))

    def _prop(self, t, p, name):
        self.state.update(CP.PT_INPUTS, p, t)
        return getattr(self.state, name)()

    def h(self, t, p):
        return self._prop(t, p, "hmass")

    def s(self, t, p):
        return self._prop(t, p, "smass")

    def _solve_t(self, p, target, func, lo=150.0, hi=500.0):
        # 二分法求 T，比直接 PH/PS 闪蒸更稳健
        for _ in range(50):
            mid = 0.5 * (lo + hi)
            if func(mid, p) < target:
                lo = mid
            else:
                hi = mid
        return 0.5 * (lo + hi)

    def t_from_ph(self, p, h):
        return self._solve_t(p, h, self.h)

    def t_from_ps(self, p, s):
        return self._solve_t(p, s, self.s)

    def expand(self, t1, p1, p2, eta_is):
        """返回 (单位质量轴功 J/kg, 出口温度 K)。"""
        h1, s1 = self.h(t1, p1), self.s(t1, p1)
        h2s = self.h(self.t_from_ps(p2, s1), p2)
        w = eta_is * (h1 - h2s)
        return w, self.t_from_ph(p2, h1 - w)


def mpa_g_to_pa(p_mpa_g):
    return p_mpa_g * 1e6 + P_ATM


def size_case(gas, p1g, p2g, pe_kw, eta_is, eta_el, t_out_c, t_station_c):
    p1, p2 = mpa_g_to_pa(p1g), mpa_g_to_pa(p2g)
    t_out_target = t_out_c + 273.15

    # 二分求所需进口温度，使出口温度 = 目标值
    lo, hi = 250.0, 480.0
    for _ in range(40):
        mid = 0.5 * (lo + hi)
        _, t2 = gas.expand(mid, p1, p2, eta_is)
        if t2 < t_out_target:
            lo = mid
        else:
            hi = mid
    t1 = 0.5 * (lo + hi)
    w, t2 = gas.expand(t1, p1, p2, eta_is)

    m = pe_kw * 1e3 / (w * eta_el)  # kg/s
    q_n = m * 3600 / gas.rho_n  # Nm³/h
    t_station = t_station_c + 273.15
    q_heat = m * (gas.h(t1, p1) - gas.h(t_station, p1)) / 1e3 if t1 > t_station else 0.0
    t_jt = gas.t_from_ph(p2, gas.h(t_station, p1))  # 调压阀等焓节流

    return {
        "p1": p1g,
        "p2": p2g,
        "ratio": p1 / p2,
        "t1_c": t1 - 273.15,
        "t2_c": t2 - 273.15,
        "w_kj": w / 1e3,
        "m": m,
        "q_n": q_n,
        "q_heat": q_heat,
        "t_jt_c": t_jt - 273.15,
        "no_preheat_t2_c": gas.expand(t_station, p1, p2, eta_is)[1] - 273.15,
    }


def print_case(r, pe_kw, eta_is):
    print(
        f"{r['p1']:>5.1f} → {r['p2']:<4.1f} | 压比 {r['ratio']:4.2f} | η_is {eta_is:.2f} | "
        f"Pe {pe_kw:4.0f} kW | 需进口 {r['t1_c']:6.1f} °C | 比功 {r['w_kj']:6.1f} kJ/kg | "
        f"流量 {r['q_n']:8.0f} Nm³/h | 预热 {r['q_heat']:5.0f} kW | "
        f"不预热出口 {r['no_preheat_t2_c']:6.1f} °C | 节流阀后 {r['t_jt_c']:6.1f} °C"
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--p1", type=float, help="进口压力 MPa(表压)")
    ap.add_argument("--p2", type=float, help="出口压力 MPa(表压)")
    ap.add_argument("--pe", type=float, default=300.0, help="目标上网电功率 kW（默认 300）")
    ap.add_argument("--eta-is", type=float, default=0.72, help="膨胀机等熵效率（螺杆约 0.65-0.75，向心透平约 0.78-0.85）")
    ap.add_argument("--eta-el", type=float, default=0.92, help="机械+齿轮+发电机(+变频)综合效率")
    ap.add_argument("--t-out", type=float, default=5.0, help="膨胀机出口最低温度 °C（默认 5）")
    ap.add_argument("--t-station", type=float, default=10.0, help="进站气体温度 °C（默认 10）")
    ap.add_argument("--table", action="store_true", help="输出典型工况对比表")
    a = ap.parse_args()

    gas = Gas()
    print(f"气质：{gas.describe()}\n标况密度 {gas.rho_n:.4f} kg/Nm³（0 °C, 101.325 kPa）\n")

    if a.table:
        cases = [(6.3, 1.6), (4.0, 1.6), (4.0, 0.8), (4.0, 0.4), (2.5, 0.4), (1.6, 0.4)]
        for eta in (0.72, 0.82):
            print(f"--- 等熵效率 {eta:.2f}（{'螺杆' if eta < 0.8 else '向心透平'}典型值），出口≥{a.t_out:.0f} °C，进站 {a.t_station:.0f} °C ---")
            for p1g, p2g in cases:
                r = size_case(gas, p1g, p2g, a.pe, eta, a.eta_el, a.t_out, a.t_station)
                print_case(r, a.pe, eta)
            print()
        return

    if a.p1 is None or a.p2 is None:
        ap.error("请给出 --p1 与 --p2，或使用 --table")
    r = size_case(gas, a.p1, a.p2, a.pe, a.eta_is, a.eta_el, a.t_out, a.t_station)
    print_case(r, a.pe, a.eta_is)


if __name__ == "__main__":
    main()
