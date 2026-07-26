#!/usr/bin/env pwsh
# FirmForge CLI launcher
$env:PYTHONPATH = "C:\MyLab\MCU"
$python = "C:\Users\radar\.workbuddy\binaries\python\envs\mcu_agent\Scripts\python.exe"
& $python -m firmforge $args
