#!/bin/bash
# Build the one-folder app with PyInstaller (run on the target OS). Used by the GitHub workflow.
set -e
python -c "import static_ffmpeg; static_ffmpeg.add_paths()"   # downloads ffmpeg/ffprobe so they get bundled
SEP=$(python -c "import os;print(os.pathsep)")
pyinstaller --noconfirm --clean --onedir --name SessionChecker \
  --collect-all streamlit --collect-all static_ffmpeg --copy-metadata streamlit \
  --hidden-import tkinter --hidden-import openpyxl --hidden-import tzdata \
  --add-data "app.py${SEP}." --add-data "check_sessions.py${SEP}." --add-data "check_before.py${SEP}." \
  launcher.py
