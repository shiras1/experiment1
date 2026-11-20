# -*- coding: utf-8 -*-
"""נקודת הכניסה של ה-exe. מצבים: ללא פרמטרים = פותח את הממשק; --checker = הבדיקה; --pick-folder = חלון בחירת תיקייה."""
import sys, os, runpy, multiprocessing
from pathlib import Path

BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))

def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--pick-folder":
        import tkinter as tk
        from tkinter import filedialog
        r = tk.Tk(); r.withdraw(); r.attributes("-topmost", True)
        sys.stdout.reconfigure(encoding="utf-8")
        print(filedialog.askdirectory(title="בחרו את תיקיית המשתתפים"))
        return
    if len(sys.argv) > 1 and sys.argv[1] == "--checker":
        try:
            import static_ffmpeg; static_ffmpeg.add_paths()
        except Exception:
            pass
        sys.argv = ["check_sessions.py"] + sys.argv[2:]
        sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
        runpy.run_path(str(BASE / "check_sessions.py"), run_name="__main__")
        return
    if len(sys.argv) > 1 and sys.argv[1] == "--before":
        sys.argv = ["check_before.py"] + sys.argv[2:]
        sys.path.insert(0, str(BASE))
        sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
        runpy.run_path(str(BASE / "check_before.py"), run_name="__main__")
        return
    cred = Path.home() / ".streamlit" / "credentials.toml"
    if not cred.exists():
        cred.parent.mkdir(exist_ok=True); cred.write_text('[general]\nemail = ""\n')
    from streamlit.web import cli as stcli
    sys.argv = ["streamlit", "run", str(BASE / "app.py"),
                "--global.developmentMode=false", "--browser.gatherUsageStats=false",
                "--server.fileWatcherType=none"]
    sys.exit(stcli.main())

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
