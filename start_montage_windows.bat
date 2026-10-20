@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title USHA GAP - montage bot

python --version >nul 2>nul
if errorlevel 1 (
    echo [!] Python не найден.
    echo     Скачай Python 3.11 или новее: https://www.python.org/downloads/
    echo     При установке обязательно поставь галочку "Add python.exe to PATH".
    echo     Потом закрой это окно и запусти файл снова.
    goto :end
)

where ffmpeg >nul 2>nul
if errorlevel 1 goto :no_ffmpeg
where ffprobe >nul 2>nul
if errorlevel 1 goto :no_ffmpeg

if not exist ".env" (
    copy ".env.example" ".env" >nul
    echo [!] Создан файл .env - сейчас он откроется в Блокноте.
    echo     Заполни строки: MONTAGE_BOT_TOKEN, GROQ_API_KEY,
    echo     TELEGRAM_API_ID, TELEGRAM_API_HASH, ADMIN_IDS
    echo     Сохрани файл, закрой Блокнот и запусти этот файл снова.
    start "" notepad ".env"
    goto :end
)

if not exist ".venv\Scripts\python.exe" (
    echo Создаю окружение Python, это один раз...
    python -m venv .venv
    if errorlevel 1 goto :end
)

echo Проверяю зависимости...
".venv\Scripts\python.exe" -m pip install -q --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
    echo [!] Не получилось установить зависимости - смотри ошибку выше.
    goto :end
)

echo.
echo Бот монтажа запущен. Чтобы остановить - закрой окно или нажми Ctrl+C.
echo.
".venv\Scripts\python.exe" -m montage_bot.main
goto :end

:no_ffmpeg
echo [!] ffmpeg не найден.
echo     Установи его одной командой в PowerShell:
echo         winget install --id Gyan.FFmpeg -e
echo     Потом закрой это окно и запусти файл снова (новое окно увидит ffmpeg).

:end
echo.
pause
