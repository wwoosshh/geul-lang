[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = 'Continue'

$compiler = 'C:\workspace\한글\자체호스팅\네이티브컴파일러.exe'

# Test 1: minimal test with --no-std
Write-Host "=== Test 1: minimal ==="
& $compiler --no-std 'C:\workspace\한글\예제\표준최소테스트.글' 2>&1
Copy-Item 'C:\workspace\한글\예제\표준최소테스트.exe' 'C:\temp\test1.exe' -Force
& 'C:\temp\test1.exe' 2>&1

# Test 2: stdlib auto-include test
Write-Host "=== Test 2: stdlib ==="
& $compiler 'C:\workspace\한글\예제\표준라이브러리테스트.글' 2>&1
Copy-Item 'C:\workspace\한글\예제\표준라이브러리테스트.exe' 'C:\temp\test2.exe' -Force
& 'C:\temp\test2.exe' 2>&1

Write-Host "=== Done ==="
