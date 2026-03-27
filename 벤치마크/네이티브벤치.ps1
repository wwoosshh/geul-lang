# 네이티브벤치.ps1 — 글 네이티브 컴파일러 vs C(MSVC /O2) vs Python 벤치마크
# 실행: powershell.exe -NoProfile -ExecutionPolicy Bypass -File "벤치마크\네이티브벤치.ps1"

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = "Continue"

$ProjectRoot = Split-Path $PSScriptRoot -Parent
$BenchDir = $PSScriptRoot
$ResultDir = Join-Path $BenchDir "결과"
if (-not (Test-Path $ResultDir)) { New-Item -ItemType Directory -Path $ResultDir | Out-Null }

# ===== 도구 경로 =====
$NativeCompiler = Join-Path $ProjectRoot "배포\네이티브컴파일러.exe"
$MSVC_CL = "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC\14.44.35207\bin\Hostx64\x64\cl.exe"
$MSVC_INCLUDE = "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC\14.44.35207\include"
$UCRT_INCLUDE = "C:\Program Files (x86)\Windows Kits\10\Include\10.0.26100.0\ucrt"
$UM_INCLUDE = "C:\Program Files (x86)\Windows Kits\10\Include\10.0.26100.0\um"
$SHARED_INCLUDE = "C:\Program Files (x86)\Windows Kits\10\Include\10.0.26100.0\shared"
$MSVC_LIB = "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC\14.44.35207\lib\x64"
$UCRT_LIB = "C:\Program Files (x86)\Windows Kits\10\Lib\10.0.26100.0\ucrt\x64"
$UM_LIB = "C:\Program Files (x86)\Windows Kits\10\Lib\10.0.26100.0\um\x64"

$pyCmd = Get-Command python -ErrorAction SilentlyContinue

# ===== 헤더 =====
$cpuName = (Get-CimInstance Win32_Processor).Name
$ramGB = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB)
$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

Write-Host ""
Write-Host "================================================================"
Write-Host "  글 네이티브 컴파일러 벤치마크  |  $timestamp"
Write-Host "  $cpuName | ${ramGB}GB RAM"
Write-Host "================================================================"
Write-Host ""

# ===== 함수 =====
function Compile-C-Simple {
    param([string]$Src, [string]$Out)
    $args_ = "/O2 /nologo /utf-8 /I`"$MSVC_INCLUDE`" /I`"$UCRT_INCLUDE`" /I`"$UM_INCLUDE`" /I`"$SHARED_INCLUDE`" /Fe:`"$Out`" `"$Src`" /link /LIBPATH:`"$MSVC_LIB`" /LIBPATH:`"$UCRT_LIB`" /LIBPATH:`"$UM_LIB`""
    cmd /c "`"$MSVC_CL`" $args_ >nul 2>nul"
    return (Test-Path $Out)
}

function Compile-Native-Gl {
    param([string]$Src, [string]$Out)
    $srcDir = Split-Path $Src -Parent
    Push-Location $srcDir
    & $NativeCompiler (Split-Path $Src -Leaf) 2>&1 | Out-Null
    Pop-Location
    $exeName = [System.IO.Path]::ChangeExtension($Src, ".exe")
    if (Test-Path $exeName) {
        if ($exeName -ne $Out) {
            Move-Item $exeName $Out -Force
        }
        return $true
    }
    return $false
}

function Measure-Runs {
    param([string]$Exe, [int]$Count = 5)
    $times = @()
    for ($i = 0; $i -lt $Count; $i++) {
        $ms = (Measure-Command { & $Exe 2>&1 | Out-Null }).TotalMilliseconds
        $times += $ms
    }
    $sorted = $times | Sort-Object
    # 중앙값 (5회: index 2)
    return @{ Median = $sorted[2]; All = $times }
}

function Measure-Py-Runs {
    param([string]$Script, [int]$Count = 5)
    $times = @()
    for ($i = 0; $i -lt $Count; $i++) {
        $ms = (Measure-Command { & python $Script 2>&1 | Out-Null }).TotalMilliseconds
        $times += $ms
    }
    $sorted = $times | Sort-Object
    return @{ Median = $sorted[2]; All = $times }
}

# ===== 벤치마크 정의 =====
$benchmarks = @(
    @{
        Name = "재귀 피보나치 fib(40)"
        GlSrc = "글\native_test.글"
        CSrc = "c\fibonacci.c"
        PySrc = "python\fibonacci.py"
    },
    @{
        Name = "에라토스테네스 체 (100만)"
        GlSrc = "글\native_primes.글"
        CSrc = "c\primes_simple.c"
        PySrc = "python\primes.py"
    },
    @{
        Name = "버블정렬 (30,000개)"
        GlSrc = "글\native_sort.글"
        CSrc = "c\bubblesort.c"
        PySrc = "python\bubblesort.py"
    }
)

$allResults = @()
$sep = [string]::new('-', 64)

foreach ($bench in $benchmarks) {
    Write-Host $sep
    Write-Host "  $($bench.Name)"
    Write-Host $sep
    Write-Host ("  {0,-20} {1,12} {2,12} {3,10}" -f "언어", "중앙값(ms)", "vs C(/O2)", "상태")

    $cMs = 0
    $results = @{}

    # --- C ---
    $cSrc = Join-Path $BenchDir $bench.CSrc
    $cExe = Join-Path $ResultDir "bench_c.exe"
    if (Test-Path $cSrc) {
        $ok = Compile-C-Simple $cSrc $cExe
        if ($ok) {
            $r = Measure-Runs $cExe
            $cMs = $r.Median
            $results["C (/O2)"] = $cMs
            Write-Host ("  {0,-20} {1,12:F1} {2,12} {3,10}" -f "C (/O2)", $cMs, "1.00x", "OK")
            Remove-Item $cExe -Force -ErrorAction SilentlyContinue
            # .obj 정리
            $cObj = Join-Path $ResultDir "bench_c.obj"
            Remove-Item $cObj -Force -ErrorAction SilentlyContinue
        } else {
            Write-Host ("  {0,-20} {1,12} {2,12} {3,10}" -f "C (/O2)", "-", "-", "컴파일실패")
        }
    }

    # --- 글 네이티브 ---
    $glSrc = Join-Path $BenchDir $bench.GlSrc
    $glExe = Join-Path $ResultDir "bench_gl.exe"
    if (Test-Path $glSrc) {
        $ok = Compile-Native-Gl $glSrc $glExe
        if ($ok) {
            $r = Measure-Runs $glExe
            $glMs = $r.Median
            $results["글 (네이티브)"] = $glMs
            $ratio = if ($cMs -gt 0) { "{0:F2}x" -f ($glMs / $cMs) } else { "N/A" }
            Write-Host ("  {0,-20} {1,12:F1} {2,12} {3,10}" -f "글 (네이티브)", $glMs, $ratio, "OK")
            Remove-Item $glExe -Force -ErrorAction SilentlyContinue
        } else {
            Write-Host ("  {0,-20} {1,12} {2,12} {3,10}" -f "글 (네이티브)", "-", "-", "컴파일실패")
        }
    }

    # --- Python ---
    if ($pyCmd -and $bench.PySrc) {
        $pySrc = Join-Path $BenchDir $bench.PySrc
        if (Test-Path $pySrc) {
            $r = Measure-Py-Runs $pySrc
            $pyMs = $r.Median
            $results["Python"] = $pyMs
            $ratio = if ($cMs -gt 0) { "{0:F2}x" -f ($pyMs / $cMs) } else { "N/A" }
            Write-Host ("  {0,-20} {1,12:F1} {2,12} {3,10}" -f "Python", $pyMs, $ratio, "OK")
        }
    }

    $allResults += @{ Name = $bench.Name; Results = $results; CMs = $cMs }
    Write-Host ""
}

# ===== 종합 요약 =====
Write-Host "================================================================"
Write-Host "  종합 요약"
Write-Host "================================================================"
Write-Host ""

foreach ($b in $allResults) {
    Write-Host "  $($b.Name):"
    foreach ($kv in $b.Results.GetEnumerator()) {
        $ratio = if ($b.CMs -gt 0) { " ({0:F2}x vs C)" -f ($kv.Value / $b.CMs) } else { "" }
        Write-Host "    $($kv.Key): $([math]::Round($kv.Value, 1))ms$ratio"
    }
}

Write-Host ""
Write-Host "  측정 방법: PowerShell Measure-Command (프로세스 시작~종료 포함)"
Write-Host "  각 테스트 5회 실행, 중앙값 사용"
Write-Host "  글: 네이티브 컴파일러 (PE 직접 생성, 최적화 없음)"
Write-Host "  C: MSVC cl.exe /O2 (최적화 활성)"
Write-Host "================================================================"

# ===== 결과 파일 저장 =====
$outFile = Join-Path $ResultDir "native_benchmark_$(Get-Date -Format 'yyyy-MM-dd-HHmmss').txt"
$output = @()
$output += "글 네이티브 컴파일러 벤치마크 결과"
$output += "일시: $timestamp"
$output += "CPU: $cpuName | RAM: ${ramGB}GB"
$output += ""
foreach ($b in $allResults) {
    $output += "$($b.Name):"
    foreach ($kv in $b.Results.GetEnumerator()) {
        $ratio = if ($b.CMs -gt 0) { " ({0:F2}x vs C)" -f ($kv.Value / $b.CMs) } else { "" }
        $output += "  $($kv.Key): $([math]::Round($kv.Value, 1))ms$ratio"
    }
    $output += ""
}
$output += "측정 방법: PowerShell Measure-Command, 5회 중앙값"
$output += "글: 네이티브 PE 직접 생성 (최적화 없음)"
$output += "C: MSVC /O2 최적화"
[System.IO.File]::WriteAllLines($outFile, $output, [System.Text.Encoding]::UTF8)
Write-Host ""
Write-Host "결과 저장됨: $outFile"
