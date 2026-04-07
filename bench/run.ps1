# 실행.ps1 — 글 언어 종합 벤치마크 중앙 제어 스크립트
# 실행: powershell.exe -NoProfile -ExecutionPolicy Bypass -File "벤치마크\실행.ps1"

# ===== UTF-8 출력 설정 =====
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

# ===== 설정 로드 =====
. (Join-Path $PSScriptRoot "설정.ps1")

# ===== 결과 디렉토리 생성 =====
if (-not (Test-Path $ResultDir)) {
    New-Item -ItemType Directory -Path $ResultDir | Out-Null
}

# ===== 트랜스크립트 시작 =====
$timestamp = Get-Date -Format "yyyy-MM-dd-HHmmss"
$transcriptPath = Join-Path $ResultDir "$timestamp.txt"
Start-Transcript -Path $transcriptPath -Force | Out-Null

# ===== 헤더 =====
$displayTime = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
$border = [string]::new([char]0x2550, 63)
$cpuName = (Get-CimInstance Win32_Processor).Name
$ramGB = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB)
$osInfo = [System.Environment]::OSVersion.VersionString

Write-Host ""
Write-Host $border
Write-Host "  글 언어 종합 벤치마크 v1.0  |  $displayTime"
Write-Host "  $osInfo | $cpuName | ${ramGB}GB RAM"
Write-Host $border

# ===== 언어 탐지 결과 표시 =====
Write-Host ""
Write-Host "  [사용 가능한 언어]"
$langOrder = @("C", "글", "Rust", "Go", "Java", "Python")
foreach ($lang in $langOrder) {
    $info = $Languages[$lang]
    if ($info.Available) {
        $extra = ""
        if ($lang -eq "C" -and $info.NeedsFullPaths) { $extra = " (vcvars 미로드, 전체 경로 사용)" }
        if ($lang -eq "글") { $extra = " (글cc → C 생성 → cl /O2 최적화 컴파일)" }
        Write-Host "    [O] $($info.Name)$extra"
    }
}
Write-Host ""
Write-Host "  [건너뛰는 언어]"
$anySkipped = $false
foreach ($lang in $langOrder) {
    $info = $Languages[$lang]
    if (-not $info.Available) {
        Write-Host "    [X] $($info.Name) — 미설치"
        $anySkipped = $true
    }
}
if (-not $anySkipped) { Write-Host "    (없음)" }

# ===== 테스트 데이터 생성 =====
Write-Host ""
Write-Host "  테스트 데이터 준비 중..."
$testDataPath = Initialize-TestData

# ===== 측정 설정 =====
$runCount = 5      # 총 실행 횟수 (0번은 워밍업)
$separator = [string]::new([char]0x2500, 63)

# ===== 메인 벤치마크 루프 =====
$allResults = @{}

for ($benchIdx = 0; $benchIdx -lt $Benchmarks.Count; $benchIdx++) {
    $bench = $Benchmarks[$benchIdx]
    Write-Host ""
    Write-Host "[$($benchIdx + 1)/$($Benchmarks.Count)] $($bench.Name) ($($bench.Desc))"
    Write-Host $separator
    Write-Host ("  {0,-10} {1,10} {2,10} {3,10}" -f "언어", "내부(ms)", "외부(ms)", "배율(vs C)")

    $benchResults = @{}

    foreach ($lang in $langOrder) {
        if (-not $Languages[$lang].Available) { continue }

        # 컴파일
        $compileResult = Compile-Benchmark $bench $lang
        if ($null -eq $compileResult) {
            Write-Host ("  {0,-10} {1,10}" -f $lang, "컴파일 실패")
            continue
        }

        # 실행 인자 준비
        $runArgs = @()
        if ($bench.NeedsFileArg) { $runArgs += $testDataPath }

        # 반복 실행
        $runs = @()
        $runFailed = $false
        for ($i = 0; $i -lt $runCount; $i++) {
            $sw = [System.Diagnostics.Stopwatch]::StartNew()
            $output = Run-Benchmark $compileResult $runArgs
            $sw.Stop()

            $externalMs = $sw.Elapsed.TotalMilliseconds

            # RESULT:xxx.xxx 파싱
            $internalMs = 0.0
            if ($output -match "RESULT:(\d+\.?\d*)") {
                $internalMs = [double]$Matches[1]
            } else {
                # RESULT 출력이 없으면 외부 시간 사용
                $internalMs = $externalMs
            }

            $runs += @{ Internal = $internalMs; External = $externalMs }
        }

        if ($runs.Count -lt $runCount) {
            Write-Host ("  {0,-10} {1,10}" -f $lang, "실행 실패")
            continue
        }

        # 워밍업(0번) 제외, 1~4번의 중앙값
        $valid = $runs[1..($runCount - 1)] | Sort-Object { $_.Internal }
        $midLow = [math]::Floor(($valid.Count - 1) / 2)
        $midHigh = [math]::Ceiling(($valid.Count - 1) / 2)
        $medianInternal = ($valid[$midLow].Internal + $valid[$midHigh].Internal) / 2
        $medianExternal = ($valid[$midLow].External + $valid[$midHigh].External) / 2

        $benchResults[$lang] = @{ Internal = $medianInternal; External = $medianExternal }
    }

    # C 기준 배율 계산 및 출력
    $cInternal = if ($benchResults.ContainsKey("C") -and $benchResults["C"].Internal -gt 0) { $benchResults["C"].Internal } else { 0 }

    foreach ($lang in $langOrder) {
        if (-not $benchResults.ContainsKey($lang)) { continue }
        $r = $benchResults[$lang]
        $ratio = if ($cInternal -gt 0) { $r.Internal / $cInternal } else { 0 }
        $ratioStr = if ($cInternal -gt 0) { "{0:F2}x" -f $ratio } else { "N/A" }
        Write-Host ("  {0,-10} {1,10:F1} {2,10:F1} {3,10}" -f $lang, $r.Internal, $r.External, $ratioStr)
    }
    Write-Host $separator

    $allResults[$bench.Name] = $benchResults

    # 임시 실행파일 정리
    foreach ($lang in $langOrder) {
        $tempExe = Join-Path $ResultDir "$($bench.Name)_$lang.exe"
        if (Test-Path $tempExe) { Remove-Item $tempExe -Force }
        # .obj 파일도 정리
        $tempObj = Join-Path $ResultDir "$($bench.Name)_$lang.obj"
        if (Test-Path $tempObj) { Remove-Item $tempObj -Force }
    }
    # Java 클래스 파일은 마지막에 한번에 정리
}

# ===== 글 전용 컴파일러 테스트 =====
$compileTestCount = 2
$totalTests = $Benchmarks.Count + $compileTestCount

# --- Test 7: 자체호스팅 소스 컴파일 시간 ---
Write-Host ""
Write-Host "[$($Benchmarks.Count + 1)/$totalTests] 컴파일 시간 (글 전용)"
Write-Host $separator

$selfHostCompileMs = 0
$selfHostLines = 0
$selfHostLinesPerSec = 0

if ($Languages["글"].Available) {
    # 자체호스팅 소스 경로 (주.글 외에도 다른 파일이 포함될 수 있음)
    $selfHostSrc = Join-Path (Join-Path $ProjectRoot "자체호스팅") "주.글"
    if (Test-Path $selfHostSrc) {
        $tempOut = Join-Path $ResultDir "temp_compile.exe"

        # 5회 측정, 중앙값
        $compileTimes = @()
        for ($i = 0; $i -lt 5; $i++) {
            $sw = [System.Diagnostics.Stopwatch]::StartNew()
            & $GlToolPath 빌드 $selfHostSrc -출력 $tempOut 2>&1 | Out-Null
            $sw.Stop()
            $compileTimes += $sw.Elapsed.TotalMilliseconds
            if (Test-Path $tempOut) { Remove-Item $tempOut -Force }
            # .obj 정리
            $tempObj = Join-Path $ResultDir "temp_compile.obj"
            if (Test-Path $tempObj) { Remove-Item $tempObj -Force }
        }
        $sorted = $compileTimes | Sort-Object
        $selfHostCompileMs = ($sorted[1] + $sorted[2]) / 2  # 중앙값(1~3번째 중)

        # 줄 수 계산
        $selfHostLines = (Get-Content $selfHostSrc -Encoding UTF8 | Measure-Object -Line).Lines
        $selfHostLinesPerSec = [math]::Round($selfHostLines / ($selfHostCompileMs / 1000))

        Write-Host ("  {0,-30} {1,10} {2,10}" -f "대상", "시간(ms)", "줄/초")
        Write-Host ("  {0,-30} {1,10:F1} {2,10}" -f "자체호스팅($($selfHostLines)줄)", $selfHostCompileMs, $selfHostLinesPerSec)
    } else {
        Write-Host "  자체호스팅 소스를 찾을 수 없습니다: $selfHostSrc"
    }
} else {
    Write-Host "  글도구.exe를 찾을 수 없어 건너뜁니다."
}
Write-Host $separator

# --- Test 8: 대규모 소스 컴파일 ---
Write-Host ""
Write-Host "[$totalTests/$totalTests] 대규모 소스 (글 전용)"
Write-Host $separator

$genCompileMs = 0
$genLines = 0
$genLinesPerSec = 0

if ($Languages["글"].Available) {
    $genSrc = Join-Path $ResultDir "generated_1000.글"
    $sb = [System.Text.StringBuilder]::new()
    [void]$sb.AppendLine('포함 "표준/기본.글"')
    [void]$sb.AppendLine('')
    for ($i = 1; $i -le 1000; $i++) {
        $num = $i.ToString('D4')
        [void]$sb.AppendLine("[정수 x를 생성함수_$num]는 -> 정수 { 반환 x + $i. }")
    }
    [void]$sb.AppendLine('')
    [void]$sb.AppendLine('[시작하기]는 {')
    [void]$sb.AppendLine('    정수 결과는 42를 생성함수_0001다.')
    [void]$sb.AppendLine('    "결과: %d\n"을 결과를 쓰기다.')
    [void]$sb.AppendLine('}')
    [System.IO.File]::WriteAllText($genSrc, $sb.ToString(), [System.Text.Encoding]::UTF8)

    $genLines = ($sb.ToString().Split("`n")).Count

    $tempGenExe = Join-Path $ResultDir "temp_gen.exe"

    # 5회 측정
    $genTimes = @()
    for ($i = 0; $i -lt 5; $i++) {
        $sw = [System.Diagnostics.Stopwatch]::StartNew()
        & $GlToolPath 빌드 $genSrc -출력 $tempGenExe 2>&1 | Out-Null
        $sw.Stop()
        $genTimes += $sw.Elapsed.TotalMilliseconds
        if (Test-Path $tempGenExe) { Remove-Item $tempGenExe -Force }
        $tempObj = Join-Path $ResultDir "temp_gen.obj"
        if (Test-Path $tempObj) { Remove-Item $tempObj -Force }
    }
    $sorted = $genTimes | Sort-Object
    $genCompileMs = ($sorted[1] + $sorted[2]) / 2
    $genLinesPerSec = [math]::Round($genLines / ($genCompileMs / 1000))

    Write-Host ("  {0,-30} {1,10} {2,10}" -f "대상", "시간(ms)", "줄/초")
    Write-Host ("  {0,-30} {1,10:F1} {2,10}" -f "생성코드($($genLines)줄,함수1000개)", $genCompileMs, $genLinesPerSec)

    # 정리
    if (Test-Path $genSrc) { Remove-Item $genSrc -Force }
} else {
    Write-Host "  글도구.exe를 찾을 수 없어 건너뜁니다."
}
Write-Host $separator

# ===== 종합 요약 =====
Write-Host ""
Write-Host $border
Write-Host "  종합 요약"
Write-Host $border

# 글 vs C 비교 분석
$strengths = @()
$weaknesses = @()

if ($allResults.Count -gt 0 -and $Languages["글"].Available -and $Languages["C"].Available) {
    foreach ($bench in $Benchmarks) {
        $br = $allResults[$bench.Name]
        if ($br.ContainsKey("글") -and $br.ContainsKey("C") -and $br["C"].Internal -gt 0) {
            $ratio = $br["글"].Internal / $br["C"].Internal
            $entry = "$($bench.Name) ({0:F2}x)" -f $ratio
            if ($ratio -le 2.0) {
                $strengths += $entry
            }
            if ($ratio -gt 5.0) {
                $weaknesses += $entry
            }
        }
    }
}

if ($strengths.Count -gt 0) {
    Write-Host "  글의 강점 (C 대비 2x 이내): $($strengths -join ', ')"
} else {
    Write-Host "  글의 강점: (데이터 부족)"
}

if ($weaknesses.Count -gt 0) {
    Write-Host "  글의 약점 (C 대비 5x 초과): $($weaknesses -join ', ')"
} else {
    Write-Host "  글의 약점: (5x 초과 없음 또는 데이터 부족)"
}

if ($selfHostLinesPerSec -gt 0) {
    Write-Host "  컴파일 속도: ${selfHostLinesPerSec}줄/초 (자체호스팅 기준)"
}
if ($genLinesPerSec -gt 0) {
    Write-Host "  컴파일 속도: ${genLinesPerSec}줄/초 (1000함수 생성코드 기준)"
}

Write-Host ""
Write-Host "  참고: 글 벤치마크는 글cc(C코드생성) + cl /O2(최적화컴파일)로 빌드됨"
Write-Host $border

# ===== Java 클래스 디렉토리 정리 =====
$javaClassDir = Join-Path $ResultDir "java_classes"
if (Test-Path $javaClassDir) { Remove-Item $javaClassDir -Recurse -Force }

# ===== 트랜스크립트 종료 =====
Write-Host ""
Write-Host "결과 저장됨: $transcriptPath"
Stop-Transcript | Out-Null
