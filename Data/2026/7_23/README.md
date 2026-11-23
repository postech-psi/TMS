# 2026-07-23 TMS session

| Pipeline metric | Value |
|---|---:|
| Peak thrust | 143.98 N |
| Average thrust | 117.40 N |
| Total impulse | 319.91 N s |
| Burn duration (5 N) | 2725.0 ms |
| Time to onset from recording start | 3803.1 ms |
| Peak pressure | 17.061 bar at 4.416 s |

`7_23 data.TXT` is SD recording `TMS_7` (an earlier local analysis used that name; the raw bytes here are the only copy). It uses the inherited loadcell calibration (−0.0391 kg/ADC, −193.0049 kg, R² 0.999948).

**Pressure is suspect.** The pressure channel starts with a 9.38 bar offset, peaks at 17.06 bar at 4.42 s while thrust is still rising, falls to about 10 bar while thrust holds at 140–144 N, and settles about 5 bar below its starting level after burnout. Thrust metrics are not affected.

`calidata/` and `cali_weights.txt` are the calibration recordings taken this day. They are kept as raw records but not used: fitted with `Calibration/calibration.py` (`ODD_ONLY = True`, which reads the interleaved loadcell channel) they give R² 0.88, too poor to replace the inherited calibration.

[Report](./analysis/2026-07-23_tms-7_executive_report.txt) · [TSV](./analysis/2026-07-23_tms-7_pipeline_data.txt) · [Quality](./analysis/2026-07-23_tms-7_quality.json) · [Combined](./analysis/2026-07-23_tms-7_combined_plot.png) · [Loadcell](./analysis/2026-07-23_tms-7_loadcell_plot.png) · [Pressure](./analysis/2026-07-23_tms-7_barometer_plot.png)

## Reproduce

Pipeline commit `0604925` (fixed 5 N threshold, inherited calibration).

```sh
python Calibration/tms_data_pipeline.py --input "Data/2026/7_23/7_23 data.TXT" --prefix 2026-07-23_tms-7 --no-show --dpi 180
```
