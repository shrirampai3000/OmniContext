@echo off
setlocal

echo Running tests...
python -m pytest %*
