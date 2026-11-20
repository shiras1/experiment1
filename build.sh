#!/bin/bash
set -e
python -c "import static_ffmpeg; static_ffmpeg.add_paths()"
SEP=$(python -c "import os;print(os.pathsep)")
pyinstaller --noconfirm --clean --onedir --name SessionChecker \
  --collect-all streamlit --collect-all static_ffmpeg --copy-metadata streamlit \
  --hidden-import tkinter --hidden-import openpyxl --hidden-import tzdata \
  --add-data "app.py${SEP}." --add-data "check_sessions.py${SEP}." \
  launcher.py
