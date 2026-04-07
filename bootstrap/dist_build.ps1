# 배포용 네이티브 컴파일러 빌드 스크립트
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = "Stop"

$root = "geul"
$basePath = "C:\workspace\$root"
$selfhost = "$basePath\src"
$bootstrap = "$basePath\bootstrap"
$geul = "gl"
$std = "std"
$outDir = "$basePath\dist"

$cl = "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC\14.44.35207\bin\Hostx64\x64\cl.exe"
$inc1 = "/I`"C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC\14.44.35207\include`""
$inc2 = "/I`"C:\Program Files (x86)\Windows Kits\10\Include\10.0.26100.0\ucrt`""
$inc3 = "/I`"C:\Program Files (x86)\Windows Kits\10\Include\10.0.26100.0\um`""
$inc4 = "/I`"C:\Program Files (x86)\Windows Kits\10\Include\10.0.26100.0\shared`""
$lib1 = "/LIBPATH:`"C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC\14.44.35207\lib\x64`""
$lib2 = "/LIBPATH:`"C:\Program Files (x86)\Windows Kits\10\Lib\10.0.26100.0\ucrt\x64`""
$lib3 = "/LIBPATH:`"C:\Program Files (x86)\Windows Kits\10\Lib\10.0.26100.0\um\x64`""

if (-not (Test-Path $outDir)) { New-Item -ItemType Directory -Path $outDir -Force | Out-Null }

Write-Host "===== Build native compiler for distribution =====" -ForegroundColor Cyan

# Step 1
Write-Host "[1/4] Transpile to C..." -ForegroundColor Yellow
$ncSrc = Join-Path $selfhost "compiler.$geul"
$glcc = Join-Path $bootstrap "build\geulcc.exe"
& $glcc $ncSrc --emit-c 2>&1 | Out-Null
$ncC = $ncSrc -replace "\.$geul$", ".c"
if (-not (Test-Path $ncC)) { throw "Transpile failed" }
Write-Host "  OK: $ncC"

# Step 2
Write-Host "[2/4] MSVC build -> nc_stage0..." -ForegroundColor Yellow
$stage0 = Join-Path $outDir "nc_stage0.exe"
& $cl /nologo /O2 /utf-8 /std:c11 /D_CRT_SECURE_NO_WARNINGS $inc1 $inc2 $inc3 $inc4 /Fe:$stage0 $ncC /link $lib1 $lib2 $lib3 2>&1 | Write-Host
if (-not (Test-Path $stage0)) { throw "MSVC build failed" }
Write-Host "  OK: $stage0 ($([math]::Round((Get-Item $stage0).Length/1024))KB)"

# Step 3
Write-Host "[3/4] nc_stage0 -> native PE..." -ForegroundColor Yellow
$stage1 = Join-Path $outDir "nc_stage1.exe"
$outArg = "-" + [char]0xCD9C + [char]0xB825
& $stage0 $ncSrc $outArg $stage1 2>&1 | Out-Null
if (-not (Test-Path $stage1)) { throw "Native build failed" }
Write-Host "  OK: $stage1 ($([math]::Round((Get-Item $stage1).Length/1024))KB)"

# Step 4
Write-Host "[4/4] Self-compile + fix_pe..." -ForegroundColor Yellow
$merged = Join-Path $outDir "merged.$geul"

# Build merged source
$content = ""
$stdBasicName = "core.$geul"
$stdBasic = Join-Path $basePath (Join-Path $std $stdBasicName)
$content += [System.IO.File]::ReadAllText($stdBasic, [System.Text.Encoding]::UTF8) + "`n"

$fileNames = @(
    "tokens", "unicode", "lexer", "ast", "parser",
    "ir", "ir_transform", "ir_codegen", "asm_gen",
    "pe_gen", "elf_gen", "compiler"
)

foreach ($fn in $fileNames) {
    $fpath = Join-Path $selfhost "$fn.$geul"
    if (Test-Path $fpath) {
        $lines = [System.IO.File]::ReadAllLines($fpath, [System.Text.Encoding]::UTF8)
        $filtered = $lines | Where-Object { $_ -notmatch "^" + [char]0xD3EC + [char]0xD568 + " " }
        $content += ($filtered -join "`n") + "`n"
    }
}
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($merged, $content, $utf8NoBom)

# 새로 빌드한 stage1을 사용하여 자체 컴파일 (고정점 검증용)
& $stage1 --no-std $merged 2>&1 | Out-Null
$rawExe = $merged -replace "\.$geul$", ".exe"
if (-not (Test-Path $rawExe)) { throw "Self-compile failed" }

# fix_pe
$finalExe = Join-Path $outDir "compiler.exe"
python3 "C:\workspace\test\fix_pe.py" $rawExe $finalExe 2>&1 | Out-Null
if (-not (Test-Path $finalExe)) { throw "fix_pe failed" }

# Verify
Write-Host "`n===== Verify =====" -ForegroundColor Cyan
$testSrc = Join-Path $outDir "verify.$geul"
$testContent = @"
외부 [문자열 형식을 ... printf]는 -> 정수.
정수 값 = 42.
[시작하기]는 -> 정수 {
    "verify: %d\n"을 값을 printf.
    반환 0.
}
"@
[System.IO.File]::WriteAllText($testSrc, $testContent, [System.Text.Encoding]::UTF8)
& $finalExe --no-std $testSrc 2>&1 | Out-Null
$testExe = $testSrc -replace "\.$geul$", ".exe"
if (Test-Path $testExe) {
    & $testExe
    Remove-Item $testExe, $testSrc -ErrorAction SilentlyContinue
} else {
    Write-Host "Verify FAILED" -ForegroundColor Red
}

# Cleanup
Remove-Item $stage0, $stage1, $merged, $rawExe -ErrorAction SilentlyContinue

$sz = [math]::Round((Get-Item $finalExe).Length / 1024)
Write-Host "`nDone: $finalExe (${sz}KB)" -ForegroundColor Green
