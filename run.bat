@echo off
setlocal
cd /d "%~dp0"
if not exist "logs" mkdir logs
echo ===== %DATE% %TIME% =====>> "logs\launch.log"
echo Dang mo Lemon3 RPA...
echo Dang mo Lemon3 RPA...>> "logs\launch.log"

if not exist ".venv\Scripts\python.exe" goto :need_venv
".venv\Scripts\python.exe" -c "import sys" >> "logs\launch.log" 2>&1
if errorlevel 1 goto :bad_venv
goto :deps

:bad_venv
echo .venv khong chay duoc tren may nay. Dang xoa de tao lai...
echo bad_venv>> "logs\launch.log"
rmdir /s /q ".venv" >> "logs\launch.log" 2>&1

:need_venv
set "PYEXE="
where py >nul 2>&1
if not errorlevel 1 (
  py -3 -c "import sys" >> "logs\launch.log" 2>&1
  if not errorlevel 1 set "PYEXE=py -3"
)
if not defined PYEXE (
  where python >nul 2>&1
  if not errorlevel 1 (
    python -c "import sys" >> "logs\launch.log" 2>&1
    if not errorlevel 1 set "PYEXE=python"
  )
)
if not defined PYEXE goto :no_python

echo Dang tao .venv bang %PYEXE% ...
echo create_venv %PYEXE%>> "logs\launch.log"
%PYEXE% -m venv .venv >> "logs\launch.log" 2>&1
if errorlevel 1 goto :venv_fail
if not exist ".venv\Scripts\python.exe" goto :venv_fail

:deps
".venv\Scripts\python.exe" -c "import sys" >> "logs\launch.log" 2>&1
if errorlevel 1 goto :venv_fail
".venv\Scripts\python.exe" -c "import customtkinter, pywinauto, openpyxl, yaml, pyautogui" >> "logs\launch.log" 2>&1
if not errorlevel 1 goto :ocr

echo.
echo Dang cai thu vien. KHONG TAT cua so nay.
echo Co internet van co the mat 3-5 phut (pip build PyAutoGUI).
echo Tien trinh se hien ngay duoi day.
echo.
echo pip_start>> "logs\launch.log"
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check --trusted-host pypi.org --trusted-host files.pythonhosted.org --upgrade pip setuptools wheel
if errorlevel 1 goto :pip_fail
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check --trusted-host pypi.org --trusted-host files.pythonhosted.org --prefer-binary --timeout 120 --retries 10 --no-build-isolation -r requirements.txt
if errorlevel 1 goto :pip_fail

:ocr
".venv\Scripts\python.exe" -c "import rapidocr_onnxruntime" >> "logs\launch.log" 2>&1
if errorlevel 1 (
  echo.
  echo Dang cai OCR de doc dong luoi. Neu loi van mo app duoc.
  echo.
  ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check --trusted-host pypi.org --trusted-host files.pythonhosted.org --prefer-binary --timeout 180 --retries 5 --no-build-isolation rapidocr-onnxruntime
)

:run
echo Mo cua so app...
echo start_app>> "logs\launch.log"

rem mo-debug.bat dat bien nay de giu console va xem loi truc tiep.
if defined LEMON3_DEBUG (
  ".venv\Scripts\python.exe" app.py
  set ERR=%ERRORLEVEL%
  echo app_exit %ERR%>> "logs\launch.log"
  if not "%ERR%"=="0" (
    echo App thoat loi %ERR%. Xem logs\launch.log
    pause
  )
  exit /b %ERR%
)

rem pythonw.exe khong kem console. start = tach han process nen dong cmd khong giet app.
set "PYW=.venv\Scripts\pythonw.exe"
if not exist "%PYW%" set "PYW=.venv\Scripts\python.exe"
start "Lemon3 RPA" "%PYW%" app.py
echo app_detached>> "logs\launch.log"
exit /b 0

:no_python
echo.
echo CHUA CAI PYTHON tren may nay.
echo Tai https://www.python.org/downloads/
echo Khi cai, tick Add python.exe to PATH, roi chay lai run.bat
echo no_python>> "logs\launch.log"
pause
exit /b 1

:venv_fail
echo.
echo Tao .venv that bai. Xoa thu muc .venv neu con, cai Python, chay lai.
echo venv_fail>> "logs\launch.log"
pause
exit /b 1

:pip_fail
echo.
echo Cai thu vien that bai.
echo Log vua cat ngang o "Installing build dependencies" = pip dang build PyAutoGUI,
echo KHONG phai mat internet. De cua so mo den khi xong, hoac chay lai run.bat.
echo Neu van loi: proxy/antivirus chan pypi.org. Xem dong do pip phia tren.
echo pip_fail>> "logs\launch.log"
pause
exit /b 1
