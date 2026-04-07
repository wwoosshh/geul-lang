# 설정.ps1 — 벤치마크 언어 탐지 및 설정
# 이 파일은 실행.ps1에서 dot-source로 로드됩니다.

# ===== 1. 경로 설정 =====
$Script:ProjectRoot = Split-Path $PSScriptRoot -Parent
$Script:BenchDir = $PSScriptRoot
$Script:ResultDir = Join-Path $BenchDir "결과"
$Script:GlToolPath = Join-Path $ProjectRoot "글도구.exe"
$Script:GlccPath = Join-Path $ProjectRoot "부트스트랩\build\글cc.exe"

# ===== 2. MSVC 경로 상수 =====
$Script:MSVC_ROOT = "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC\14.44.35207"
$Script:MSVC_CL = Join-Path $MSVC_ROOT "bin\Hostx64\x64\cl.exe"
$Script:MSVC_INCLUDE = Join-Path $MSVC_ROOT "include"
$Script:WINSDK_INCLUDE_UCRT = "C:\Program Files (x86)\Windows Kits\10\Include\10.0.26100.0\ucrt"
$Script:WINSDK_INCLUDE_UM = "C:\Program Files (x86)\Windows Kits\10\Include\10.0.26100.0\um"
$Script:WINSDK_INCLUDE_SHARED = "C:\Program Files (x86)\Windows Kits\10\Include\10.0.26100.0\shared"
$Script:MSVC_LIB = Join-Path $MSVC_ROOT "lib\x64"
$Script:WINSDK_LIB_UCRT = "C:\Program Files (x86)\Windows Kits\10\Lib\10.0.26100.0\ucrt\x64"
$Script:WINSDK_LIB_UM = "C:\Program Files (x86)\Windows Kits\10\Lib\10.0.26100.0\um\x64"

# ===== 3. 언어 탐지 =====
$Script:Languages = @{}

# --- C (MSVC) ---
$clAvailable = $false
$clPath = $null
$clNeedsFullPaths = $false

# vcvars 로드 여부 확인: cl.exe가 PATH에 있는지
$clCmd = Get-Command cl.exe -ErrorAction SilentlyContinue
if ($clCmd) {
    $clAvailable = $true
    $clPath = $clCmd.Source
    $clNeedsFullPaths = $false
} elseif (Test-Path $MSVC_CL) {
    $clAvailable = $true
    $clPath = $MSVC_CL
    $clNeedsFullPaths = $true
}

$Script:Languages["C"] = @{
    Available = $clAvailable
    Name = "C (MSVC)"
    ClPath = $clPath
    NeedsFullPaths = $clNeedsFullPaths
}

# --- 글 ---
# 글도구.exe (자체호스팅)에 재귀 함수 파싱 버그가 있어 글cc.exe (부트스트랩) 사용
$glAvailable = Test-Path $GlccPath
if (-not $glAvailable) { $glAvailable = Test-Path $GlToolPath }
$Script:Languages["글"] = @{
    Available = $glAvailable
    Name = "글"
}

# --- Python ---
$pyCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pyCmd) { $pyCmd = Get-Command python3 -ErrorAction SilentlyContinue }
$Script:Languages["Python"] = @{
    Available = ($null -ne $pyCmd)
    Name = "Python"
    Cmd = if ($pyCmd) { $pyCmd.Source } else { $null }
}

# --- Go ---
$goCmd = Get-Command go -ErrorAction SilentlyContinue
$Script:Languages["Go"] = @{
    Available = ($null -ne $goCmd)
    Name = "Go"
}

# --- Rust ---
$rustCmd = Get-Command rustc -ErrorAction SilentlyContinue
$Script:Languages["Rust"] = @{
    Available = ($null -ne $rustCmd)
    Name = "Rust"
}

# --- Java ---
$javacCmd = Get-Command javac -ErrorAction SilentlyContinue
$javaCmd = Get-Command java -ErrorAction SilentlyContinue
$Script:Languages["Java"] = @{
    Available = ($null -ne $javacCmd) -and ($null -ne $javaCmd)
    Name = "Java"
}

# ===== 4. 벤치마크 목록 =====
$Script:Benchmarks = @(
    @{ Name="피보나치"; Desc="fib(40) 재귀"; GlFile="피보나치.글"; CFile="fibonacci.c"; PyFile="fibonacci.py"; GoFile="fibonacci.go"; RsFile="fibonacci.rs"; JavaClass="Fibonacci"; NeedsFileArg=$false },
    @{ Name="정렬"; Desc="100만 정수 퀵소트"; GlFile="정렬.글"; CFile="sort.c"; PyFile="sort.py"; GoFile="sort.go"; RsFile="sort.rs"; JavaClass="Sort"; NeedsFileArg=$false },
    @{ Name="행렬곱"; Desc="500x500 행렬 곱셈"; GlFile="행렬곱.글"; CFile="matrix.c"; PyFile="matrix.py"; GoFile="matrix.go"; RsFile="matrix.rs"; JavaClass="Matrix"; NeedsFileArg=$false },
    @{ Name="소수판별"; Desc="에라토스테네스 체 100만"; GlFile="소수판별.글"; CFile="primes.c"; PyFile="primes.py"; GoFile="primes.go"; RsFile="primes.rs"; JavaClass="Primes"; NeedsFileArg=$false },
    @{ Name="파일처리"; Desc="10MB 파일 단어 수 세기"; GlFile="파일처리.글"; CFile="fileio.c"; PyFile="fileio.py"; GoFile="fileio.go"; RsFile="fileio.rs"; JavaClass="FileIO"; NeedsFileArg=$true },
    @{ Name="메모리할당"; Desc="100만 malloc/free + 연결리스트"; GlFile="메모리할당.글"; CFile="memory.c"; PyFile="memory.py"; GoFile="memory.go"; RsFile="memory.rs"; JavaClass="Memory"; NeedsFileArg=$false }
)

# ===== 5. 테스트 데이터 생성 =====
function Initialize-TestData {
    $testFile = Join-Path $ResultDir "testdata.txt"
    if (Test-Path $testFile) { return $testFile }

    if (-not (Test-Path $ResultDir)) {
        New-Item -ItemType Directory -Path $ResultDir | Out-Null
    }

    $lorem = "Lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod tempor incididunt ut labore et dolore magna aliqua Ut enim ad minim veniam quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur Excepteur sint occaecat cupidatat non proident sunt in culpa qui officia deserunt mollit anim id est laborum"

    $targetSize = 10 * 1024 * 1024  # 10MB
    $sb = [System.Text.StringBuilder]::new($targetSize + 1000)
    while ($sb.Length -lt $targetSize) {
        [void]$sb.AppendLine($lorem)
    }
    [System.IO.File]::WriteAllText($testFile, $sb.ToString(), [System.Text.Encoding]::UTF8)
    Write-Host "  테스트 데이터 생성 완료: $testFile ($([math]::Round((Get-Item $testFile).Length / 1MB, 1))MB)"
    return $testFile
}

# ===== 6. 컴파일/실행 함수 =====

function Compile-C {
    param([string]$SrcFile, [string]$OutExe)
    $lang = $Script:Languages["C"]
    if (-not $lang.Available) { return $false }

    if ($lang.NeedsFullPaths) {
        $clArgs = @(
            "/O2", "/nologo", "/utf-8", "/std:c11",
            "/I`"$MSVC_INCLUDE`"",
            "/I`"$WINSDK_INCLUDE_UCRT`"",
            "/I`"$WINSDK_INCLUDE_UM`"",
            "/I`"$WINSDK_INCLUDE_SHARED`"",
            "/Fe:`"$OutExe`"",
            "`"$SrcFile`"",
            "/link",
            "/LIBPATH:`"$MSVC_LIB`"",
            "/LIBPATH:`"$WINSDK_LIB_UCRT`"",
            "/LIBPATH:`"$WINSDK_LIB_UM`""
        )
        $cmdLine = "`"$($lang.ClPath)`" $($clArgs -join ' ')"
        cmd /c "$cmdLine >nul 2>nul"
    } else {
        & $lang.ClPath /O2 /nologo /utf-8 /std:c11 /Fe:"$OutExe" "$SrcFile" /link > $null 2>&1
    }
    return (Test-Path $OutExe)
}

function Compile-Gl {
    param([string]$SrcFile, [string]$OutExe)
    if (-not $Script:Languages["글"].Available) { return $false }
    # 2단계 컴파일: 글cc로 C 코드 생성 → cl /O2로 최적화 컴파일
    $srcDir = Split-Path $SrcFile -Parent
    $srcName = [System.IO.Path]::GetFileNameWithoutExtension($SrcFile)
    $genC = Join-Path $srcDir "$srcName.c"

    if (Test-Path $GlccPath) {
        # 1단계: 글cc --emit-c로 C 코드만 생성
        & $GlccPath "$SrcFile" --emit-c 2>&1 | Out-Null
        if (-not (Test-Path $genC)) { return $false }

        # 2단계: C 코드를 /O2로 컴파일 (C 벤치마크와 동일 조건)
        $result = Compile-C $genC $OutExe

        # 정리: 생성된 .c, .obj, 글cc가 만든 .exe
        Remove-Item $genC -ErrorAction SilentlyContinue
        $genObj = Join-Path $srcDir "$srcName.obj"
        Remove-Item $genObj -ErrorAction SilentlyContinue
        $genExe = Join-Path $srcDir "$srcName.exe"
        if ((Test-Path $genExe) -and ($genExe -ne $OutExe)) { Remove-Item $genExe -ErrorAction SilentlyContinue }

        return $result
    } else {
        & $GlToolPath 빌드 "$SrcFile" -출력 "$OutExe" 2>&1 | Out-Null
        return (Test-Path $OutExe)
    }
}

function Compile-Go {
    param([string]$SrcFile, [string]$OutExe)
    & go build -o "$OutExe" "$SrcFile" 2>&1 | Out-Null
    return (Test-Path $OutExe)
}

function Compile-Rust {
    param([string]$SrcFile, [string]$OutExe)
    & rustc -C opt-level=2 -o "$OutExe" "$SrcFile" 2>&1 | Out-Null
    return (Test-Path $OutExe)
}

function Compile-Java {
    param([string]$SrcFile, [string]$OutDir)
    & javac -d "$OutDir" "$SrcFile" 2>&1 | Out-Null
    return $?
}

function Get-BenchmarkSource {
    param([hashtable]$Bench, [string]$Lang)
    switch ($Lang) {
        "C"      { return Join-Path (Join-Path $BenchDir "c") $Bench.CFile }
        "글"     { return Join-Path (Join-Path $BenchDir "글") $Bench.GlFile }
        "Python" { return Join-Path (Join-Path $BenchDir "python") $Bench.PyFile }
        "Go"     { return Join-Path (Join-Path $BenchDir "go") $Bench.GoFile }
        "Rust"   { return Join-Path (Join-Path $BenchDir "rust") $Bench.RsFile }
        "Java"   { return Join-Path (Join-Path $BenchDir "java") "$($Bench.JavaClass).java" }
    }
}

function Compile-Benchmark {
    param([hashtable]$Bench, [string]$Lang)
    $src = Get-BenchmarkSource $Bench $Lang
    if (-not (Test-Path $src)) { return $null }

    $outExe = Join-Path $ResultDir "$($Bench.Name)_$Lang.exe"

    switch ($Lang) {
        "C"    { if (Compile-C $src $outExe) { return $outExe } }
        "글"   { if (Compile-Gl $src $outExe) { return $outExe } }
        "Go"   { if (Compile-Go $src $outExe) { return $outExe } }
        "Rust" { if (Compile-Rust $src $outExe) { return $outExe } }
        "Java" {
            $classDir = Join-Path $ResultDir "java_classes"
            if (-not (Test-Path $classDir)) { New-Item -ItemType Directory -Path $classDir | Out-Null }
            if (Compile-Java $src $classDir) { return "java:$classDir`:$($Bench.JavaClass)" }
        }
        "Python" {
            # 인터프리터 언어, 컴파일 불필요
            return "python:$src"
        }
    }
    return $null
}

function Run-Benchmark {
    param([string]$ExePath, [string[]]$RunArgs)

    if ($ExePath.StartsWith("python:")) {
        $pyFile = $ExePath.Substring(7)
        $pyCmd = $Script:Languages["Python"].Cmd
        if ($RunArgs.Count -gt 0) {
            return & $pyCmd $pyFile @RunArgs 2>&1 | Out-String
        } else {
            return & $pyCmd $pyFile 2>&1 | Out-String
        }
    }
    elseif ($ExePath.StartsWith("java:")) {
        $parts = $ExePath.Split(":")
        $classDir = $parts[1]
        $className = $parts[2]
        if ($RunArgs.Count -gt 0) {
            return & java -cp $classDir $className @RunArgs 2>&1 | Out-String
        } else {
            return & java -cp $classDir $className 2>&1 | Out-String
        }
    }
    else {
        if ($RunArgs.Count -gt 0) {
            return & $ExePath @RunArgs 2>&1 | Out-String
        } else {
            return & $ExePath 2>&1 | Out-String
        }
    }
}
