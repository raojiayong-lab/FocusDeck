@echo off
setlocal
set PY=C:\Users\Lenovo\AppData\Local\Programs\Python\Python314\python.exe
set ROOT=C:\Users\Lenovo\Desktop\love
set TMPWORK=C:\Users\Lenovo\AppData\Local\Temp\fd_build
set TMPDIST=C:\Users\Lenovo\AppData\Local\Temp\fd_dist

"%PY%" -m PyInstaller --noconfirm --onefile --noconsole ^
  --name FocusDeck ^
  --icon "%ROOT%\icon.ico" ^
  --add-data "%ROOT%\index.html;." ^
  --add-data "%ROOT%\icon.ico;." ^
  --workpath "%TMPWORK%" ^
  --distpath "%TMPDIST%" ^
  "%ROOT%\app.py"

if %errorlevel% neq 0 (
  echo 构建失败
  pause
  exit /b %errorlevel%
)

if not exist "%ROOT%\dist" mkdir "%ROOT%\dist"
copy /Y "%TMPDIST%\FocusDeck.exe" "%ROOT%\dist\FocusDeck.exe"

echo 构建完成：%ROOT%\dist\FocusDeck.exe
pause
