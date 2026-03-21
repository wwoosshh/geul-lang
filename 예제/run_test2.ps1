chcp 65001 | Out-Null
# Test existing printf native test
$output1 = cmd /c "C:\workspace\한글\예제\네이티브_출력테스트.exe" 2>&1
Write-Output "printf_test: [$output1]"

# Test new stdlib test
$output2 = cmd /c "C:\workspace\한글\예제\표준라이브러리테스트.exe" 2>&1
Write-Output "stdlib_test: [$output2]"
