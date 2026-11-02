$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$env:PYTHONPATH = "$PSScriptRoot;$PSScriptRoot\vendor"
python -m streamlit run app.py
