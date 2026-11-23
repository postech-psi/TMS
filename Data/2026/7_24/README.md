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

[Raw](./TMS_5.TXT) · [Report](./analysis/2026-07-24_tms-5_executive_report.txt) · [TSV](./analysis/2026-07-24_tms-5_pipeline_data.txt) · [Quality](./analysis/2026-07-24_tms-5_quality.json) · [Combined](./analysis/2026-07-24_tms-5_combined_plot.png) · [Loadcell](./analysis/2026-07-24_tms-5_loadcell_plot.png) · [Pressure](./analysis/2026-07-24_tms-5_barometer_plot.png)

## Reproduce

Pipeline commit `0604925` (fixed 5 N threshold, inherited calibration).

```sh
python Calibration/tms_data_pipeline.py --input Data/2026/7_24/TMS_5.TXT --prefix 2026-07-24_tms-5 --no-show --dpi 180
```
