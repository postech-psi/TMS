param(
    [Parameter(Mandatory = $true)]
    [string]$TestDate,

    [Parameter(Mandatory = $true)]
    [string]$AnalysisDir,

    [Parameter(Mandatory = $true)]
    [string]$ResultsRepoPath,

    [string]$VideoUrl = "",
    [string[]]$Issues = @(),
    [string]$ResultStem = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Require-File {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Required file not found: $Path"
    }
}

function Require-Directory {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        throw "Required directory not found: $Path"
    }
}

function Get-LineValue {
    param(
        [string[]]$Lines,
        [string]$Prefix
    )
    $match = $Lines | Where-Object { $_.StartsWith($Prefix) } | Select-Object -First 1
    if (-not $match) {
        return $null
    }
    return $match.Substring($Prefix.Length).Trim()
}

function Get-ReportData {
    param([string]$ReportPath)

    $lines = Get-Content -LiteralPath $ReportPath -Encoding utf8
    $peakPressureLine = Get-LineValue -Lines $lines -Prefix "Peak pressure:"

    $peakPressureValue = ""
    $peakPressureTime = ""
    if ($peakPressureLine -match '^(?<value>[0-9.]+)\s+at\s+(?<time>[0-9.]+\s+s)$') {
        $peakPressureValue = "$($Matches.value) bar gauge pressure"
        $peakPressureTime = $Matches.time
    } else {
        $peakPressureValue = $peakPressureLine
    }

    return [ordered]@{
        InputFile = Get-LineValue -Lines $lines -Prefix "Input file:"
        SamplingRate = Get-LineValue -Lines $lines -Prefix "Sampling rate:"
        IgnitionDelay = Get-LineValue -Lines $lines -Prefix "Ignition delay:"
        PeakThrust = Get-LineValue -Lines $lines -Prefix "Peak thrust:"
        TotalImpulse = Get-LineValue -Lines $lines -Prefix "Total impulse:"
        AverageThrust = Get-LineValue -Lines $lines -Prefix "Average thrust:"
        BurnDuration = Get-LineValue -Lines $lines -Prefix "Burn duration:"
        PeakPressure = $peakPressureValue
        PeakPressureTime = $peakPressureTime
        ThrustFilter = Get-LineValue -Lines $lines -Prefix "Loadcell filter:"
        PressureFilter = Get-LineValue -Lines $lines -Prefix "Pressure filter:"
        DriftCorrection = Get-LineValue -Lines $lines -Prefix "Drift correction:"
        LoadcellBaselineOffset = Get-LineValue -Lines $lines -Prefix "Loadcell baseline offset:"
        LoadcellBaselineWindowEnd = Get-LineValue -Lines $lines -Prefix "Loadcell baseline window end:"
        PressureBaselineOffset = Get-LineValue -Lines $lines -Prefix "Pressure baseline offset:"
        IgnitionStartTime = Get-LineValue -Lines $lines -Prefix "Ignition start time:"
    }
}

function Convert-ToTitleDate {
    param([string]$DateText)
    $parsed = [datetime]::ParseExact($DateText, "yyyy-MM-dd", $null)
    return "{0}/{1}/{2}" -f $parsed.Year, $parsed.Month, $parsed.Day
}

function Convert-ToReadmeDate {
    param([string]$DateText)
    return $DateText.Replace("-", ".")
}

function New-MarkdownPage {
    param(
        [string]$TitleDate,
        [string]$AssetDir,
        [hashtable]$ReportData,
        [string[]]$Issues,
        [string]$VideoUrl
    )

    $inputFileName = ($ReportData.InputFile -split '[\\/]')[-1]

    $issuesBlock = if ($Issues.Count -gt 0) {
        ($Issues | ForEach-Object { "- $_" }) -join "`r`n"
    } else {
        "- 없음"
    }

    $videoBlock = if ([string]::IsNullOrWhiteSpace($VideoUrl)) {
        "- 링크 없음"
    } else {
        "- [시험 영상 보기]($VideoUrl)"
    }

    @"
# $TitleDate 연소 시험

## Graphs

### Loadcell+Barometer Plot

![Combined Plot](./assets/$AssetDir/$([uri]::EscapeDataString("$ResultStem`_combined_plot.png")))

### Loadcell Plot

![Loadcell Plot](./assets/$AssetDir/$([uri]::EscapeDataString("$ResultStem`_loadcell_plot.png")))

### Barometer Plot

![Barometer Plot](./assets/$AssetDir/$([uri]::EscapeDataString("$ResultStem`_barometer_plot.png")))

## Metrics

| 항목 | 값 |
|---|---:|
| 입력 파일 | $inputFileName |
| 샘플링 속도 | $($ReportData.SamplingRate) |
| 점화 지연 | $($ReportData.IgnitionDelay) |
| 연소 시간 | $($ReportData.BurnDuration) |
| 최대 추력 | $($ReportData.PeakThrust) |
| 평균 추력 | $($ReportData.AverageThrust) |
| 총 임펄스 | $($ReportData.TotalImpulse) |
| 최대 압력 | $($ReportData.PeakPressure) |
| 최대 압력 시점 | $($ReportData.PeakPressureTime) |

## Test And Plot Conditions

| 항목 | 값 |
|---|---|
| 데이터 취득 시스템 | TMS (Arduino Nano 기반) |
| 센서 | Loadcell, Barometer |
| 추력 필터 | $($ReportData.ThrustFilter) |
| 압력 필터 | $($ReportData.PressureFilter) |
| 드리프트 보정 | 기준선 오프셋 보정 ($($ReportData.DriftCorrection)) |
| 로드셀 기준 오프셋 | $($ReportData.LoadcellBaselineOffset) |
| 로드셀 기준 구간 종료 | $($ReportData.LoadcellBaselineWindowEnd) |
| 압력 보정 | Gauge baseline 제거 |
| 압력 기준 오프셋 | $($ReportData.PressureBaselineOffset) |

## Issues

$issuesBlock

## Test Video

$videoBlock

## Result Files

- [Executive Report 다운로드](./assets/$AssetDir/$([uri]::EscapeDataString("$ResultStem`_executive_report.txt")))
- [Pipeline Data 다운로드](./assets/$AssetDir/$([uri]::EscapeDataString("$ResultStem`_pipeline_data.txt")))
"@
}

function New-HtmlPage {
    param(
        [string]$TitleDate,
        [string]$AssetDir,
        [hashtable]$ReportData,
        [string[]]$Issues,
        [string]$VideoUrl
    )

    $inputFileName = ($ReportData.InputFile -split '[\\/]')[-1]

    $issuesHtml = if ($Issues.Count -gt 0) {
        ($Issues | ForEach-Object { "        <li>$_</li>" }) -join "`r`n"
    } else {
        "        <li>없음</li>"
    }

    $videoHtml = if ([string]::IsNullOrWhiteSpace($VideoUrl)) {
        "      <span>링크 없음</span>"
    } else {
        "      <a href=`"$VideoUrl`">시험 영상 보기</a>"
    }

    @"
<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>$TitleDate 연소 시험</title>
  <style>
    :root {
      --bg: #f6f7f9;
      --card: #ffffff;
      --text: #1a1f26;
      --muted: #5d6776;
      --line: #d8dee8;
      --accent: #0f5cc0;
    }
    * { box-sizing: border-box; }
    body { margin: 0; font-family: "Segoe UI", Arial, sans-serif; background: var(--bg); color: var(--text); line-height: 1.5; }
    .wrap { max-width: 980px; margin: 0 auto; padding: 32px 20px 56px; }
    h1, h2, h3 { margin: 0 0 12px; }
    h1 { font-size: 34px; }
    h2 { margin-top: 36px; padding-bottom: 8px; border-bottom: 1px solid var(--line); font-size: 24px; }
    h3 { margin-top: 22px; font-size: 18px; }
    .card { background: var(--card); border: 1px solid var(--line); border-radius: 16px; padding: 18px; margin-top: 14px; }
    img { width: 100%; display: block; border-radius: 12px; border: 1px solid var(--line); background: #fff; }
    table { width: 100%; border-collapse: collapse; background: var(--card); border: 1px solid var(--line); border-radius: 16px; overflow: hidden; }
    th, td { padding: 12px 14px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }
    th { background: #eef3fb; }
    tr:last-child td { border-bottom: 0; }
    ul { margin: 0; padding-left: 20px; }
    a { color: var(--accent); text-decoration: none; }
    a:hover { text-decoration: underline; }
  </style>
</head>
<body>
  <div class="wrap">
    <h1>$TitleDate 연소 시험</h1>

    <h2>Graphs</h2>

    <h3>Loadcell+Barometer Plot</h3>
    <div class="card">
      <img src="./assets/$AssetDir/$([uri]::EscapeDataString("$ResultStem`_combined_plot.png"))" alt="Loadcell+Barometer Plot">
    </div>

    <h3>Loadcell Plot</h3>
    <div class="card">
      <img src="./assets/$AssetDir/$([uri]::EscapeDataString("$ResultStem`_loadcell_plot.png"))" alt="Loadcell Plot">
    </div>

    <h3>Barometer Plot</h3>
    <div class="card">
      <img src="./assets/$AssetDir/$([uri]::EscapeDataString("$ResultStem`_barometer_plot.png"))" alt="Barometer Plot">
    </div>

    <h2>Metrics</h2>
    <table>
      <tr><th>항목</th><th>값</th></tr>
      <tr><td>입력 파일</td><td><code>$inputFileName</code></td></tr>
      <tr><td>샘플링 속도</td><td>$($ReportData.SamplingRate)</td></tr>
      <tr><td>점화 지연</td><td>$($ReportData.IgnitionDelay)</td></tr>
      <tr><td>연소 시간</td><td>$($ReportData.BurnDuration)</td></tr>
      <tr><td>최대 추력</td><td>$($ReportData.PeakThrust)</td></tr>
      <tr><td>평균 추력</td><td>$($ReportData.AverageThrust)</td></tr>
      <tr><td>총 임펄스</td><td>$($ReportData.TotalImpulse)</td></tr>
      <tr><td>최대 압력</td><td>$($ReportData.PeakPressure)</td></tr>
      <tr><td>최대 압력 시점</td><td>$($ReportData.PeakPressureTime)</td></tr>
    </table>

    <h2>Test And Plot Conditions</h2>
    <table>
      <tr><th>항목</th><th>값</th></tr>
      <tr><td>데이터 취득 시스템</td><td>TMS (Arduino Nano 기반)</td></tr>
      <tr><td>센서</td><td>Loadcell, Barometer</td></tr>
      <tr><td>추력 필터</td><td>$($ReportData.ThrustFilter)</td></tr>
      <tr><td>압력 필터</td><td>$($ReportData.PressureFilter)</td></tr>
      <tr><td>드리프트 보정</td><td>기준선 오프셋 보정 ($($ReportData.DriftCorrection))</td></tr>
      <tr><td>로드셀 기준 오프셋</td><td>$($ReportData.LoadcellBaselineOffset)</td></tr>
      <tr><td>로드셀 기준 구간 종료</td><td>$($ReportData.LoadcellBaselineWindowEnd)</td></tr>
      <tr><td>압력 보정</td><td>Gauge baseline 제거</td></tr>
      <tr><td>압력 기준 오프셋</td><td>$($ReportData.PressureBaselineOffset)</td></tr>
    </table>

    <h2>Issues</h2>
    <div class="card">
      <ul>
$issuesHtml
      </ul>
    </div>

    <h2>Test Video</h2>
    <div class="card">
$videoHtml
    </div>

    <h2>Result Files</h2>
    <div class="card">
      <ul>
        <li><a href="./assets/$AssetDir/$([uri]::EscapeDataString("$ResultStem`_executive_report.txt"))">Executive Report 다운로드</a></li>
        <li><a href="./assets/$AssetDir/$([uri]::EscapeDataString("$ResultStem`_pipeline_data.txt"))">Pipeline Data 다운로드</a></li>
      </ul>
    </div>
  </div>
</body>
</html>
"@
}

function New-RootReadme {
    param([System.Collections.Generic.List[object]]$Entries)

    $entryLines = foreach ($entry in $Entries) {
@"
## $($entry.ReadmeDate). 연소시험

- 웹페이지: [$($entry.TitleDate) 연소 시험](./tests/$($entry.TestDate)/index.html)
- Markdown: [tests/$($entry.TestDate)/index.md](./tests/$($entry.TestDate)/index.md)
- HTML: [tests/$($entry.TestDate)/index.html](./tests/$($entry.TestDate)/index.html)
"@
    }

@"
# PSI Test Results

PSI 시험 결과 공개 및 정리용 저장소입니다.

$($entryLines -join "`r`n")
"@
}

function New-RootIndexMarkdown {
    param([System.Collections.Generic.List[object]]$Entries)

    $lines = foreach ($entry in $Entries) {
        "- [$($entry.TitleDate) 연소 시험](./tests/$($entry.TestDate)/index.html)"
    }

@"
# PSI Test Results

## Published Tests

$($lines -join "`r`n")
"@
}

function New-RootIndexHtml {
    param([System.Collections.Generic.List[object]]$Entries)

    $listItems = foreach ($entry in $Entries) {
        "        <li><a href=`"./tests/$($entry.TestDate)/index.html`">$($entry.TitleDate) 연소 시험</a></li>"
    }

@"
<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>PSI Test Results</title>
  <style>
    body { font-family: "Segoe UI", Arial, sans-serif; max-width: 900px; margin: 0 auto; padding: 32px 20px 56px; line-height: 1.6; color: #1a1f26; }
    h1 { margin-bottom: 8px; }
    .muted { color: #5d6776; }
    ul { padding-left: 20px; }
    a { color: #0f5cc0; text-decoration: none; }
    a:hover { text-decoration: underline; }
  </style>
</head>
<body>
  <h1>PSI Test Results</h1>
  <p class="muted">PSI 시험 결과 공개 및 정리용 저장소입니다.</p>

  <h2>Published Tests</h2>
  <ul>
$($listItems -join "`r`n")
  </ul>
</body>
</html>
"@
}

$repoRoot = (Resolve-Path -LiteralPath ".").Path
$analysisPath = (Resolve-Path -LiteralPath $AnalysisDir).Path
$resultsRepo = (Resolve-Path -LiteralPath $ResultsRepoPath).Path

Require-Directory -Path $analysisPath
Require-Directory -Path $resultsRepo

if ([string]::IsNullOrWhiteSpace($ResultStem)) {
    $reportFiles = Get-ChildItem -LiteralPath $analysisPath -Filter "*_executive_report.txt"
    if ($reportFiles.Count -ne 1) {
        throw "Could not auto-detect a single report stem in $analysisPath. Use -ResultStem explicitly."
    }
    $ResultStem = $reportFiles[0].BaseName -replace '_executive_report$',''
}

$requiredFiles = @(
    "$ResultStem`_combined_plot.png",
    "$ResultStem`_loadcell_plot.png",
    "$ResultStem`_barometer_plot.png",
    "$ResultStem`_executive_report.txt",
    "$ResultStem`_pipeline_data.txt"
)

foreach ($file in $requiredFiles) {
    Require-File -Path (Join-Path $analysisPath $file)
}

$reportPath = Join-Path $analysisPath "$ResultStem`_executive_report.txt"
$reportData = Get-ReportData -ReportPath $reportPath
$titleDate = Convert-ToTitleDate -DateText $TestDate
$readmeDate = Convert-ToReadmeDate -DateText $TestDate

$testDir = Join-Path $resultsRepo ("tests\" + $TestDate)
$assetDir = Join-Path $testDir "assets\$TestDate"
New-Item -ItemType Directory -Force -Path $assetDir | Out-Null

foreach ($file in $requiredFiles) {
    Copy-Item -LiteralPath (Join-Path $analysisPath $file) -Destination (Join-Path $assetDir $file) -Force
}

$mdContent = New-MarkdownPage -TitleDate $titleDate -AssetDir $TestDate -ReportData $reportData -Issues $Issues -VideoUrl $VideoUrl
$htmlContent = New-HtmlPage -TitleDate $titleDate -AssetDir $TestDate -ReportData $reportData -Issues $Issues -VideoUrl $VideoUrl

Set-Content -LiteralPath (Join-Path $testDir "index.md") -Value $mdContent -Encoding utf8
Set-Content -LiteralPath (Join-Path $testDir "index.html") -Value $htmlContent -Encoding utf8

$testsRoot = Join-Path $resultsRepo "tests"
New-Item -ItemType Directory -Force -Path $testsRoot | Out-Null
$entries = New-Object 'System.Collections.Generic.List[object]'

foreach ($directory in (Get-ChildItem -LiteralPath $testsRoot -Directory | Sort-Object Name -Descending)) {
    if ($directory.Name -notmatch '^\d{4}-\d{2}-\d{2}$') {
        continue
    }
    $entries.Add([pscustomobject]@{
        TestDate = $directory.Name
        TitleDate = Convert-ToTitleDate -DateText $directory.Name
        ReadmeDate = Convert-ToReadmeDate -DateText $directory.Name
    })
}

Set-Content -LiteralPath (Join-Path $resultsRepo "README.md") -Value (New-RootReadme -Entries $entries) -Encoding utf8
Set-Content -LiteralPath (Join-Path $resultsRepo "index.md") -Value (New-RootIndexMarkdown -Entries $entries) -Encoding utf8
Set-Content -LiteralPath (Join-Path $resultsRepo "index.html") -Value (New-RootIndexHtml -Entries $entries) -Encoding utf8

Write-Host "Published test result for $TestDate"
Write-Host "Results repo: $resultsRepo"
Write-Host "Test page: $(Join-Path $testDir 'index.html')"
