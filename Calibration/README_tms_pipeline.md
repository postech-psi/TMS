# TMS analysis pipeline

Use `tms_data_pipeline.py` for normal static fire analysis. `tms_exponential_temp.py` remains experimental.

```sh
python Calibration/tms_data_pipeline.py --input Data/2026/10_13/TMS_4.TXT --prefix 2026-10-13_tms-4 --no-show
python -m unittest discover -s Calibration -p 'test_tms_pipeline.py'
```

`--output-dir`, `--dpi`, and `--no-plots` support repeatable batch processing. Defaults retain the historical configured dataset. Install `requirements.txt`; NumPy 2+ supplies `trapezoid`.

## Use the most recent pushed pipeline

Before analyzing new data, fetch the TMS remote and confirm the pipeline is from the latest pushed default branch, not an old local checkout. Record the exact code commit and SHA-256 with the outputs. If the pipeline needs a fix, publish and verify that fix first, then re-run the data from the pushed code. `quality.json` records the most recent commit that changed this script and marks uncommitted code explicitly.

## Input and timing

Timed files contain two integer uptime header lines (`sampling_start_time`, `power_on_time`, in microseconds), then alternating loadcell and pressure ADC values. Skip the two header **lines before** splitting channels. Before 2026-10-13 the loader skipped two values per channel, losing the first sensor pair and shifting the nominal origin by 3.125 ms. Historical published data is retained and identified as legacy output.

Two-line files are firmware startup probes, not firings. Odd payloads and values outside signed 16-bit range are rejected. Device uptime is not a calendar timestamp. Use a user-confirmed date for the directory; the new session is `Data/2026/10_13/`.

The time axis remains `arange(n)/320`, as in previous analyses. The firmware targets a 15-second loop but synchronous SD/I2C operations may lengthen intervals. Without per-sample timestamps, actual timing and impulse uncertainty cannot be recovered. Do not rescale the recordings to 15 seconds without evidence.

## Processing and quality

Inherited conversion: `(−193.0049 − 0.0391 * adc) * 9.80665` N; pressure `0.0027 * adc − 0.11` bar. No new calibration is inferred from this session. The historical R² belongs to that calibration, not the new test.

Thrust uses a constant pre-event baseline and a zero-phase Butterworth filter (20 Hz, order 2). Pressure uses 5 Hz, order 4, and the first 0.5 seconds as baseline. First/last crossings of 3% peak define the legacy event window. Time to onset is from recording start, not independently measured ignition-command latency.

Before calculating performance, a conservative event gate requires force above `max(5 N, 10 * initial raw standard deviation)` for 0.1 seconds. Recordings without an event receive no performance metrics. Pressure is checked on raw ADC values before baseline subtraction: clipped or constant channels receive unavailable (`nan` in TSV, `null` in JSON) pressure, never zero bar.

A final one-second offset at least half the 3% threshold makes thrust metrics provisional. A last crossing at the final sample marks burn end censored. The historical algorithm's numeric output is preserved for diagnosis; it is not validated motor performance. Plots show the full recording when channels fail.

## Outputs and organization

Raw files remain unchanged under `Data/<year>/<month_day>/`. Canonical derived filenames are `<YYYY-MM-DD>_tms-<file-number>_<artifact>`, lowercase ASCII. The file number identifies an SD recording, not a test number.

Each timed recording produces `executive_report.txt`, `pipeline_data.txt`, `quality.json`, and `loadcell_plot.png`, `barometer_plot.png`, `combined_plot.png`. TSV retains the original seven columns and appends both raw ADC columns. Quality JSON contains raw/source code hashes, header values, samples, gate settings, calibration assumptions, channel status, warnings, and derived metrics. Keep the session inventory and comparisons with the raw files.

For the October session, TMS_4 alone has a clear thrust event; TMS_2 and TMS_5 are no-event recordings; TMS_1 and TMS_3 are startup probes. All pressure samples are 32767. See the session README for measured results and limits.
