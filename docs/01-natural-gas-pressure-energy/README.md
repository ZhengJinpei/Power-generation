# 专题 01：天然气余压（管网压力能）发电

| 文档 | 内容 |
|---|---|
| [01-technical-routes.md](01-technical-routes.md) | 技术路线：膨胀机型式、传动/发电机方式、预热热源、系统布置 |
| [02-selection-300-450kVA.md](02-selection-300-450kVA.md) | 300–450 kVA 级选型：流量与热负荷测算、螺杆 vs 透平对比、推荐方案 |
| [03-data-checklist.md](03-data-checklist.md) | 整套设备资料清单：设计输入、设备技术资料、设计交付、报批并网、标准规范 |
| [../../tools/pressure_letdown_calc.py](../../tools/pressure_letdown_calc.py) | 热力估算脚本（预热温度、所需流量、预热热负荷） |
| [../../tools/annual_compare.py](../../tools/annual_compare.py) | 透平 vs 螺杆全年发电量对比（可读入实测逐时流量 CSV） |

## 结论速览

1. **技术路线**：核心是“膨胀机替代/并联调压阀”。膨胀机有向心透平、轴流透平、双螺杆、转子式（罗茨/转子泵反转）、旋转活塞、涡旋、活塞等；配合不同的发电机传动方式（齿轮箱+常规电机、直联、高速永磁+变频、全封闭）、预热热源（燃气炉、余热、CHP、热泵、空温）及“电+冷”联产。
2. **300–450 kVA（约 240–360 kW）**：推荐首选 **无油双螺杆膨胀机 + 防爆发电机，与调压器并联，前置热水预热**；压比 2–4 且流量稳定时可改选 **向心透平**。300 kW 需常年基础流量约 0.6–1.8 万 Nm³/h，预热热量约为发电量的 1.1–1.5 倍。
3. **资料**：最先要拿到的是逐时流量（≥1 年）、进出站压力温度、气质分析、热源条件和电价气价，用于可行性测算；然后是站场图纸、电气接入条件和供应商技术资料。

## 运行计算工具

```bash
pip install CoolProp
python tools/pressure_letdown_calc.py --table                 # 典型工况对比表
python tools/pressure_letdown_calc.py --p1 4.0 --p2 1.6 --pe 300 --eta-is 0.72
```
