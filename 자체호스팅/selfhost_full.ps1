[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$hangeul = "" + [char]0xD55C + [char]0xAE00
$selfhost = "" + [char]0xC790 + [char]0xCCB4 + [char]0xD638 + [char]0xC2A4 + [char]0xD305
$ju = "" + [char]0xC8FC
$geul = "" + [char]0xAE00
$basePath = "C:\workspace\$hangeul"

# Stage 0: bootstrap-compiled self-hosting compiler
$stage0 = "$basePath\$selfhost\$ju.exe"
$source = "$basePath\$selfhost\$ju.$geul"

# Rename stage0 to avoid overwriting itself
$stage0copy = "$basePath\$selfhost\${ju}_stage0.exe"
Copy-Item $stage0 $stage0copy -Force

Write-Host "=== Stage 1: Self-hosting compiler compiles itself ==="
Write-Host "Compiler: $stage0copy"
Write-Host "Source: $source"
Write-Host ""

& $stage0copy $source 2>&1 | ForEach-Object { Write-Host $_ }

$stage1 = "$basePath\$selfhost\$ju.exe"
if (Test-Path $stage1) {
    $size = (Get-Item $stage1).Length
    Write-Host ""
    Write-Host "Stage 1 SUCCESS: $stage1 ($size bytes)"

    # Stage 2: Stage 1 compiler compiles itself again
    Write-Host ""
    Write-Host "=== Stage 2: Stage 1 compiler compiles itself ==="

    $stage1copy = "$basePath\$selfhost\${ju}_stage1.exe"
    Copy-Item $stage1 $stage1copy -Force

    & $stage1copy $source 2>&1 | ForEach-Object { Write-Host $_ }

    $stage2 = "$basePath\$selfhost\$ju.exe"
    if (Test-Path $stage2) {
        $size2 = (Get-Item $stage2).Length
        Write-Host ""
        Write-Host "Stage 2 SUCCESS: $stage2 ($size2 bytes)"

        # Compare stage1 and stage2 output
        $stage2copy = "$basePath\$selfhost\${ju}_stage2.exe"
        Copy-Item $stage2 $stage2copy -Force

        $hash1 = (Get-FileHash $stage1copy -Algorithm SHA256).Hash
        $hash2 = (Get-FileHash $stage2copy -Algorithm SHA256).Hash

        Write-Host ""
        Write-Host "=== Fixed-point check ==="
        Write-Host "Stage1 SHA256: $hash1"
        Write-Host "Stage2 SHA256: $hash2"
        if ($hash1 -eq $hash2) {
            Write-Host "FIXED POINT REACHED! Self-hosting is complete!"
        } else {
            Write-Host "Not yet a fixed point (different binaries)"
            Write-Host "Stage1 size: $size bytes"
            Write-Host "Stage2 size: $size2 bytes"
        }
    } else {
        Write-Host "Stage 2 FAILED"
    }
} else {
    Write-Host "Stage 1 FAILED"
}
