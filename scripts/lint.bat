@echo off
setlocal

echo Running ruff check...
python -m ruff check .

echo Running ruff format...
python -m ruff format .
