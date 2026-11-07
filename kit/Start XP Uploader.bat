@echo off
title XP Uploader - bonitabluehair.com
echo Leave this window open while you play. Close it to stop uploading.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0XPUploader.ps1"
pause
