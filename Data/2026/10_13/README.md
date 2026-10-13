# 2026-10-13 TMS session

Original recordings and video are retained with the pipeline outputs.

| Pipeline metric | Value |
|---|---:|
| Peak thrust | 166.01 N |
| Average thrust | 122.36 N |
| Total impulse | 336.53 N s |
| Burn duration (extrapolated 3% window) | 2750.3 ms |
| Pressure | Unavailable |

[Executive report](./analysis/2026-10-13_tms-4_executive_report.txt) · [Pipeline data](./analysis/2026-10-13_tms-4_pipeline_data.txt) · [Raw recording](./TMS_4.TXT) · [Original video](./video/2026-10-13_tms-4_video_original.mp4) · [Browser video](./video/2026-10-13_tms-4_video.mp4)

## Reproduce

Fetch and verify the latest pushed pipeline before analysis. The present outputs use code commit `3cb9efb9c3d2530ef30778036a3ccae50695ffc6`; code hashes and processing status are retained in the machine-readable output metadata.

```sh
python Calibration/tms_data_pipeline.py --input Data/2026/10_13/TMS_4.TXT --prefix 2026-10-13_tms-4 --burnout-fit-window 9.65 9.85 --no-show --dpi 180
```

Time assumes 320 Hz. The original onset is retained. The 9.65–9.85 s measured decay is fitted and extrapolated to 3% peak, giving an estimated end at 10.072218 s (zero at 10.094675 s). Impulse and average thrust use the analysis curve and this endpoint. The original measured force remains in filtered_force_N; analysis_force_N stores the extrapolated tail.
