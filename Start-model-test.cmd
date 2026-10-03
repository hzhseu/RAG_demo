@echo off
if exist "%~dp0dist\ModelTester\ModelTester.exe" (
  "%~dp0dist\ModelTester\ModelTester.exe" --config "%~dp0runtime.json"
) else (
  pushd "%~dp0"
  "%~dp0.venv\Scripts\python.exe" -m nordrag.model_test
  popd
)
if errorlevel 1 pause
