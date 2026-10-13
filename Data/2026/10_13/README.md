# 2026-10-13 TMS session

Original recordings and video are retained with the pipeline outputs.

| Pipeline metric | Value |
|---|---:|
| Peak thrust | 166.01 N |
| Average thrust | 54.82 N |
| Total impulse | 370.22 N s |
| Burn duration (3% threshold window) | 6753.1 ms |
| Pressure | Unavailable |

[Executive report](./analysis/2026-10-13_tms-4_executive_report.txt) · [Pipeline data](./analysis/2026-10-13_tms-4_pipeline_data.txt) · [Raw recording](./TMS_4.TXT) · [Original video](./video/2026-10-13_tms-4_video_original.mp4) · [Browser video](./video/2026-10-13_tms-4_video.mp4)

## Reproduce

Fetch and verify the latest pushed pipeline before analysis. The present outputs use code commit `7ebf8ec9f1725619d1d1ff75c37109e3514c5047`; code hashes and processing status are retained in the machine-readable output metadata.

```sh
python Calibration/tms_data_pipeline.py --input Data/2026/10_13/TMS_4.TXT --prefix 2026-10-13_tms-4 --no-show --dpi 180
```

Time assumes 320 Hz. The reported burn window is from the first to last crossing of 3% peak filtered thrust; average thrust is impulse divided by that window.
