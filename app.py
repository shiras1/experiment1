# -*- coding: utf-8 -*-
"""בדיקת סוף ניסוי - ממשק בדפדפן. מופעל ע"י start_windows.bat / start_mac.command."""
import os, subprocess, sys, tempfile
from pathlib import Path
import pandas as pd
import streamlit as st

HERE = Path(__file__).parent
# Command that re-runs this program in a helper mode (works both as script and as frozen exe)
SELF = [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, str(HERE / "launcher.py")]
st.set_page_config(page_title="בדיקת סוף ניסוי", page_icon="✅", layout="wide")
st.markdown("""<style>
html, body, [data-testid="stAppViewContainer"], [data-testid="stSidebar"] {direction: rtl; text-align: right;}
.stTextInput input, .stNumberInput input {direction: rtl;}
</style>""", unsafe_allow_html=True)

# ffprobe: מגיע עם החבילה static-ffmpeg (יורד בהפעלה הראשונה), אם לא מותקן במערכת
@st.cache_resource
def setup_ffprobe():
    try:
        import static_ffmpeg
        static_ffmpeg.add_paths()
    except Exception:
        pass
    return True
setup_ffprobe()

COLORS = {"PASS": "#c6efce", "WARN": "#ffeb9c", "FAIL": "#ffc7ce", "INFO": "#ddebf7"}
LABEL = {"PASS": "תקין", "WARN": "לבדוק", "FAIL": "כשל", "INFO": "מידע"}

def pick_folder():
    try:
        p = subprocess.run(SELF + ["--pick-folder"], capture_output=True, text=True, timeout=300, encoding="utf-8")
        return p.stdout.strip()
    except Exception:
        return ""

def color(df, col):
    shown = df.copy()
    shown[col] = shown[col].map(lambda v: LABEL.get(v, v))
    inv = {LABEL[k]: v for k, v in COLORS.items()}
    return shown.style.map(lambda v: f"background-color:{inv.get(v,'')}", subset=[col])

st.title("בדיקה אוטומטית של סוף הניסוי")
st.write("שלושה צעדים: בחרו את תיקיית המשתתפים, (לא חובה) העלו קובץ שיבוץ, ולחצו **הפעל בדיקה**.")

if "folder" not in st.session_state:
    st.session_state.folder = ""
st.subheader("1. תיקיית המשתתפים")
c1, c2 = st.columns([4, 1])
with c2:
    st.write("")
    if st.button("בחירת תיקייה…"):
        chosen = pick_folder()
        if chosen:
            st.session_state.folder = chosen
            st.rerun()
        else:
            st.warning("חלון בחירת התיקייה לא נפתח או בוטל. אפשר להדביק את נתיב התיקייה בשדה.")
with c1:
    folder = st.text_input("נתיב התיקייה (אפשר גם להדביק ידנית)", key="folder")

if folder:
    p = Path(folder)
    if p.is_dir():
        found = [i.name for i in p.iterdir() if i.suffix.lower() == ".zip" or (i.is_dir() and i.name[:1] in "Dd" and i.name[1:2].isdigit())]
        if found:
            st.success(f"נמצאו {len(found)} משתתפים: {', '.join(sorted(found)[:6])}{'…' if len(found) > 6 else ''}")
        else:
            st.warning("בתיקייה אין קבצי zip או תיקיות של משתתפים (D…). בדקו שבחרתם את התיקייה הנכונה.")
    else:
        st.error("התיקייה לא קיימת.")

st.subheader("2. קובץ שיבוץ (לא חובה)")
up = st.file_uploader("csv עם העמודות participant ו-test_ID", type=["csv"])

with st.expander("הגדרות מתקדמות (ברירות המחדל מתאימות)"):
    a, b, c = st.columns(3)
    pairs = a.number_input("זוגות צפויים", 1, 50, 8)
    mn = b.number_input("משך מינימלי (דק׳)", 0.0, 500.0, 10.0)
    mx = c.number_input("משך מקסימלי (דק׳)", 0.0, 500.0, 90.0)
    pg = a.number_input("שניות מינימום לעמוד", 0.0, 600.0, 20.0)
    eq = b.number_input("% תשובות ״שווה״ מקסימלי", 0.0, 100.0, 40.0)
    ld = c.number_input("פער הקלטה/שאלון (דק׳)", 0.0, 500.0, 20.0)

st.subheader("3. הפעלה")
if st.button("הפעל בדיקה", type="primary", disabled=not (folder and Path(folder).is_dir())):
    outdir = Path(tempfile.mkdtemp(prefix="chk_out_"))
    cmd = SELF + ["--checker", folder, "--out", str(outdir),
           "--expected-pairs", str(pairs), "--min-minutes", str(mn), "--max-minutes", str(mx),
           "--min-page-seconds", str(pg), "--max-equal-pct", str(eq), "--max-lead-minutes", str(ld)]
    if up is not None:
        ap = outdir / "assignment.csv"; ap.write_bytes(up.getvalue()); cmd += ["--assignment", str(ap)]
    with st.spinner("הבדיקה רצה. עם הקלטות גדולות זה יכול לקחת כמה דקות…"):
        pr = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    xlsx = outdir / "session_check_report.xlsx"
    if pr.returncode != 0 or not xlsx.exists():
        st.error("הבדיקה נכשלה לפני שנוצר דוח. העתיקו את ההודעה ושלחו לשירה:")
        st.code((pr.stdout + "\n" + pr.stderr)[-3000:])
    else:
        S = pd.read_excel(xlsx, sheet_name="סיכום"); D = pd.read_excel(xlsx, sheet_name="פירוט")
        nf = int((S["סטטוס כולל"] == "FAIL").sum()); nw = int((S["סטטוס כולל"] == "WARN").sum())
        msg = f"נבדקו {len(S)} משתתפים: {len(S)-nf-nw} תקינים, {nw} לבדוק, {nf} כשלים."
        (st.error if nf else st.warning if nw else st.success)(("יש כשלים שחובה לטפל בהם. " if nf else "") + msg)
        st.dataframe(color(S[["משתתף", "test_ID", "סטטוס כולל"]], "סטטוס כולל"), hide_index=True)
        bad = D[D["סטטוס"].isin(["FAIL", "WARN"])].sort_values("סטטוס")
        if len(bad):
            st.subheader("מה דורש טיפול")
            st.dataframe(color(bad, "סטטוס"), hide_index=True)
        st.caption("הבדיקה אינה מכסה הסכמה, שאלון דמוגרפי, רישיון נהיגה ואישור אפוטרופוס.")
        st.download_button("הורדת הדוח (Excel)", xlsx.read_bytes(), "session_check_report.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
