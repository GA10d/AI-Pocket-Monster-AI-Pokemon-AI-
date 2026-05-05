@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Please install Python 3.10+ and try again.
  pause
  exit /b 1
)

python -c "import pygame" >nul 2>nul
if errorlevel 1 (
  echo pygame is not installed. Installing pygame...
  python -m pip install pygame
  if errorlevel 1 (
    echo Failed to install pygame.
    pause
    exit /b 1
  )
)

python frontend.py
if errorlevel 1 (
  echo.
  echo The game exited with an error.
  pause
  exit /b 1
)
