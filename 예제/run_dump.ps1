[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:Path = $env:Path
$compiler = Join-Path $PSScriptRoot '..\자체호스팅\네이티브컴파일러.exe'
$source = Join-Path $PSScriptRoot '표준라이브러리테스트.글'
& $compiler --dump-ir $source 2>&1 | Out-File -FilePath 'C:\temp\ir_dump.txt' -Encoding utf8
