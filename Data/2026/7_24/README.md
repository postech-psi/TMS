# 2026-07-24 TMS session

| Pipeline metric | Value |
|---|---:|
| Peak thrust | 58.45 N |
| Average thrust | 46.94 N |
| Total impulse | 155.65 N s |
| Burn duration (5 N) | 3315.6 ms |
| Time to onset from recording start | 6146.9 ms |
| Peak pressure | 38.177 bar at 7.494 s |

Inherited loadcell calibration (−0.0391 kg/ADC, −193.0049 kg, R² 0.999948).

## Issues

- **Thrust plateau does not follow pressure.** Force holds at 57–58 N from 7.25 to 8.75 s while chamber pressure falls from 38.0 to 19.4 bar, then drops with pressure at burnout. A motor's thrust normally tracks chamber pressure.
- **Not ADC saturation.** The plateau sits at −5031 ± 2 counts with about half the resting noise (2.0 vs 4.0 counts SD); the same loadcell read −5261 counts the previous day. A mechanical limit in the load path (stand reaching a stop or binding) would produce this shape.
- **Inconsistent with 2026-07-23:** 144 N at 17 bar there, against 58 N at 38 bar here.

The recording is the logger's original data and is published as measured. Peak thrust, impulse and average thrust are therefore suspect and should not be read as motor performance; the pressure trace has the shape of a normal burn.

[Raw](./TMS_5.TXT) · [Report](./analysis/2026-07-24_tms-5_executive_report.txt) · [TSV](./analysis/2026-07-24_tms-5_pipeline_data.txt) · [Quality](./analysis/2026-07-24_tms-5_quality.json) · [Combined](./analysis/2026-07-24_tms-5_combined_plot.png) · [Loadcell](./analysis/2026-07-24_tms-5_loadcell_plot.png) · [Pressure](./analysis/2026-07-24_tms-5_barometer_plot.png)

## Reproduce

Pipeline commit `0604925` (fixed 5 N threshold, inherited calibration).

```sh
python Calibration/tms_data_pipeline.py --input Data/2026/7_24/TMS_5.TXT --prefix 2026-07-24_tms-5 --no-show --dpi 180
```
