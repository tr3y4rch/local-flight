@echo off
powershell -ExecutionPolicy Bypass -WindowStyle Hidden -Command "& '%~dp0..\..\.venv\Scripts\Activate.ps1'; cd '%~dp0..\..\src'; python -m localflight"
