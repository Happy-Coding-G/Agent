@echo off
REM Celery Worker 启动脚本 for Windows
REM 用法: run_celery.bat worker

cd /d "%~dp0"

echo Starting Celery Worker...
echo.

REM 使用 Windows 兼容模式 (solo pool)
python -m celery -A app.core.celery_config %* --pool=solo

pause
