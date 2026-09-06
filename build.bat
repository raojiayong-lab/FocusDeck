@echo off
setlocal
:: 一键打包 FocusDeck.exe
:: 前置：Python 3.14 + pywebview + PyInstaller
::    pip install pywebview PyInstaller
:: 在仓库根目录双击运行即可（PY 指向你的 python 解释器）。
:: 注意：刻意关闭 UPX（--noupx），避免被杀软误报 / 解压阶段崩溃。
set PY=python
set ROOT=%~dp0
set TMPWORK=%TEMP%\fd_build
set TMPDIST=%TEMP%\fd_dist

"%PY%" -m PyInstaller --noconfirm --onefile --noconsole --noupx ^
  --name FocusDeck ^
  --icon "%ROOT%icon.ico" ^
  --add-data "%ROOT%index.html;." ^
  --add-data "%ROOT%icon.ico;." ^
  --workpath "%TMPWORK%" ^
  --distpath "%TMPDIST%" ^
  "%ROOT%app.py"

if %errorlevel% neq 0 (
  echo 构建失败
  pause
  exit /b %errorlevel%
)

if not exist "%ROOT%dist" mkdir "%ROOT%dist"
copy /Y "%TMPDIST%\FocusDeck.exe" "%ROOT%dist\FocusDeck.exe"

echo 构建完成：%ROOT%dist\FocusDeck.exe
pause
