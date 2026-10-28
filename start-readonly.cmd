@echo off
chcp 65001 >nul 2>&1
title SoloDrama Studio (read-only)
cd /d "%~dp0"
echo.
echo   Starting in READ-ONLY mode:
echo   write actions, billing actions and model config changes are all rejected.
echo.
call "%~dp0start.cmd" --readonly %*
