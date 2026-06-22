# Helper: activate ESP-IDF 5.5 in a clean (non-MSYS) environment.
# Dot-source this before running idf.py:  . .\_idf-activate.ps1
Remove-Item Env:MSYSTEM -ErrorAction SilentlyContinue
Remove-Item Env:MINGW_PREFIX -ErrorAction SilentlyContinue
Remove-Item Env:MSYSTEM_PREFIX -ErrorAction SilentlyContinue
$env:PATH = (($env:PATH -split ';') | Where-Object { $_ -notmatch '\\Git\\mingw64|\\Git\\usr|\\Git\\cmd' }) -join ';'
$env:IDF_PATH = "C:\Espressif\frameworks\esp-idf-v5.5.4"
$env:IDF_TOOLS_PATH = "C:\Espressif"
$env:IDF_PYTHON_ENV_PATH = "C:\Espressif\python_env\idf5.5_py3.11_env"
. "C:\Espressif\frameworks\esp-idf-v5.5.4\export.ps1" | Out-Null
