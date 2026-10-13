# 2026-10-13 TMS session

Date confirmed by the user. Original TMS_1.TXT–TMS_5.TXT bytes are preserved in this directory.

- TMS_4: one clear thrust event, provisional 166.01 N peak and 370.22 N s impulse.
- TMS_2/TMS_5: full recordings without a sustained thrust event.
- TMS_1/TMS_3: firmware startup probes, not timed tests.
- Pressure: ADC 32767 in all files; unavailable, not zero bar.
- Burn duration and average thrust: unvalidated because a 4.961 N residual offset is near the 4.980 N threshold.

[Detailed review and comparison](./analysis/2026-10-13_analysis.md) · [Session manifest](./analysis/2026-10-13_session_manifest.json) · [Original video](./video/2026-10-13_tms-4_video_original.mp4) · [Browser video](./video/2026-10-13_tms-4_video.mp4)

## Reproduce

Always fetch and verify the latest pushed pipeline before new analysis. These results were rerun after fetching pushed code commit `7c717b7dfc8bdc745e766173d23c5b90ebf4827e`. The exact code commit and SHA-256 appear in each quality JSON. Install the repository requirements; this run used NumPy 2.5.4, SciPy 1.18.1, and Matplotlib 3.11.2.

```sh
python Calibration/tms_data_pipeline.py --input Data/2026/10_13/TMS_4.TXT --prefix 2026-10-13_tms-4 --no-show --dpi 180
```

Use TMS_2 or TMS_5 for no-event diagnostic outputs. Startup probes are rejected by the timed-recording parser. All times and impulse assume 320 Hz; individual sample timestamps and same-day calibration were not supplied.

Publication inventory paths in the manifest refer to test-results. Locally, raw files are in this directory, outputs are in analysis, and video assets are in video.
