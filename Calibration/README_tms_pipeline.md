# TMS analysis pipeline

Use `tms_data_pipeline.py` for normal static fire analysis. `tms_exponential_temp.py` remains experimental.

```sh
python Calibration/tms_data_pipeline.py --input Data/2026/10_13/TMS_4.TXT --prefix 2026-10-13_tms-4 --burnout-fit-window 9.65 9.85 --no-show
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

Thrust uses a constant pre-event baseline and a zero-phase Butterworth filter (20 Hz, order 2). Pressure uses 5 Hz, order 4, and the first 0.5 seconds as baseline. First/last crossings of a fixed 5 N filtered-force threshold (`THRUST_EVENT_THRESHOLD_N`) define the event window. Outputs before 2026-11-23 used 3% of peak and keep that label in their reports. Time to onset is from recording start, not independently measured ignition-command latency.

Before calculating performance, a conservative event gate requires force above `max(5 N, 10 * initial raw standard deviation)` for 0.1 seconds. Recordings without an event receive no performance metrics. Pressure is checked on raw ADC values before baseline subtraction: clipped or constant channels receive unavailable (`nan` in TSV, `null` in JSON) pressure, never zero bar.

A final one-second offset at least half the 5 N threshold makes thrust metrics provisional. A last crossing at the final sample marks burn end censored. The historical algorithm's numeric output is preserved for diagnosis; it is not validated motor performance. Plots show the full recording when channels fail.

## Outputs and organization

Raw files remain unchanged under `Data/<year>/<month_day>/`. Canonical derived filenames are `<YYYY-MM-DD>_tms-<file-number>_<artifact>`, lowercase ASCII. The file number identifies an SD recording, not a test number.

Each timed recording produces `executive_report.txt`, `pipeline_data.txt`, `quality.json`, and `loadcell_plot.png`, `barometer_plot.png`, `combined_plot.png`. TSV retains the original seven columns and appends both raw ADC columns. Quality JSON contains raw/source code hashes, header values, samples, gate settings, calibration assumptions, channel status, warnings, and derived metrics. Keep the session inventory and comparisons with the raw files.

For the October session, TMS_4 alone has a clear thrust event; TMS_2 and TMS_5 are no-event recordings; TMS_1 and TMS_3 are startup probes. All pressure samples are 32767. See the session README for measured results and limits.

## Optional burnout extrapolation

For an anomalous tail, `--burnout-fit-window START_S END_S` fits the measured filtered decay before that tail. The October TMS_4 processing uses 9.65–9.85 s. This is an explicit per-record processing choice, not an automatic rule for every firing.

Least squares supplies a descending slope, intercept, and R². A fit must follow the force peak, contain at least 10 samples, have R² ≥ 0.95, and cross the 5 N threshold after the selected window but reach zero within the recording. The published end uses the 5 N threshold; the zero crossing is also recorded. The October TMS_4 outputs were produced with the earlier 3% definition.

`filtered_force_N`, corrected force, ADC values, and all raw bytes remain measured data. An additional `analysis_force_N` column replaces the tail beginning at the fit end with the fitted line, clipped at zero. Impulse integrates this analysis curve from the original onset to the exact fractional-sample threshold endpoint, and average thrust uses the same interval. The original last-crossing end and impulse remain in the quality JSON for traceability. Plots retain the measured tail and show the extrapolation separately.

No fitting window means the original threshold method is unchanged. Fit settings and results are in `thrust.tail_extrapolation` in the machine-readable output. These are estimated burnout results; the method does not establish the physical cause of the measured tail or recover missing logger timestamps.

## Burn split across two recordings

The firmware writes fixed 15-second files. A long ignition delay can push the burn across a file boundary, leaving an unsampled interval between the files. `tms_split_recording.py` analyzes such a pair as one firing:

```sh
python Calibration/tms_split_recording.py Data/2026/11_23/TMS_2.TXT Data/2026/11_23/TMS_3.TXT --prefix 2026-11-23_tms-2-3 --templates Data/2026/4_2/analysis/*pipeline_data.txt Data/2026/4_8/analysis/*pipeline_data.txt Data/2026/5_28/analysis/*pipeline_data.txt Data/2026/7_16/analysis/*pipeline_data.txt Data/2026/7_23/analysis/TMS_7_pipeline_data.txt Data/2026/7_24/analysis/*pipeline_data.txt Data/2026/10_13/analysis/2026-10-13_tms-4_pipeline_data.txt
```

- The second file is placed using the difference of the two sampling-start headers (same power cycle required). The first file's pre-event loadcell baseline is applied to both files, and each file is filtered separately.
- Earlier firings' peak-normalized thrust curves (`--templates`) are fitted to the force next to the gap: the last 1 s of the first file plus the measured decay. Amplitude, time shift and time stretch are free. Each fill is pinned to both edge levels, taken from a quadratic fit to the unfiltered force over 0.25 s at each edge (the last filtered sample is pulled by the zero-phase filter's end behaviour). Templates with RMS error ≤ 6 N are accepted; their median is the gap estimate and their spread is the range. A knee fit (end trend continued into the back-projected decay) and a straight bridge are kept for comparison.
- Measured and fitted impulse are reported separately. Measured impulse alone is a lower bound.
- A drifting chamber-pressure channel is despiked (0.1 s running median) and a smooth baseline through thrust-free periods is subtracted. If the result correlates with thrust below r = 0.5 during the burn, it is labelled unverified and kept out of performance metrics.
- Figures use the pipeline's standard loadcell, barometer and combined plots with the unsampled interval hatched and the fitted portion dashed.
