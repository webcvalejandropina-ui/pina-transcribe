@echo off
rem Arranca Pina Transcribe en Docker desde Windows (doble clic o desde CMD).
cd /d "%~dp0"
where py >nul 2>nul && (py -3 launch_docker.py %*) || (python launch_docker.py %*)
