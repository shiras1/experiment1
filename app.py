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

def show_report(pr, xlsx, name):
    if pr.returncode != 0 or not xlsx.exists():
        st.error("הבדיקה נכשלה לפני שנוצר דוח. העתיקו את ההודעה ושלחו לשירה:")
        st.code((pr.stdout + "\n" + pr.stderr)[-3000:]); return
    S = pd.read_excel(xlsx, sheet_name="סיכום"); D = pd.read_excel(xlsx, sheet_name="פירוט")
    nf = int((S["סטטוס כולל"] == "FAIL").sum()); nw = int((S["סטטוס כולל"] == "WARN").sum())
    msg = f"נבדקו {len(S)} משתתפים: {len(S)-nf-nw} תקינים, {nw} לבדוק, {nf} כשלים."
    (st.error if nf else st.warning if nw else st.success)(("יש כשלים שחובה לטפל בהם. " if nf else "") + msg)
    st.dataframe(color(S[["משתתף", "test_ID", "סטטוס כולל"]], "סטטוס כולל"), hide_index=True)
    bad = D[D["סטטוס"].isin(["FAIL", "WARN"])].sort_values("סטטוס")
    if len(bad):
        st.subheader("מה דורש טיפול")
        st.dataframe(color(bad, "סטטוס"), hide_index=True)
    st.download_button("הורדת הדוח (Excel)", xlsx.read_bytes(), name,
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key=name)

def save_upload(up, outdir, fname):
    if up is None:
        return None
    p = outdir / (fname + Path(up.name).suffix.lower()); p.write_bytes(up.getvalue()); return str(p)

def drive_installed():
    """True/False on Windows and Mac; None where we cannot tell"""
    try:
        if os.name == "nt":
            pf = [os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")]
            return any((Path(x) / "Google" / "Drive File Stream").exists() for x in pf)
        if sys.platform == "darwin":
            return Path("/Applications/Google Drive.app").exists()
    except Exception:
        pass
    return None

DRIVE_PAGE = "https://www.google.com/drive/download/"

def install_drive():
    """Download Google's official installer and start it (the user still confirms and signs in). Returns a message."""
    import urllib.request, webbrowser
    try:
        if os.name == "nt":
            url, dst = "https://dl.google.com/drive-file-stream/GoogleDriveSetup.exe", Path(tempfile.gettempdir()) / "GoogleDriveSetup.exe"
        elif sys.platform == "darwin":
            url, dst = "https://dl.google.com/drive-file-stream/GoogleDrive.dmg", Path(tempfile.gettempdir()) / "GoogleDrive.dmg"
        else:
            webbrowser.open(DRIVE_PAGE); return "נפתח דף ההורדה של Google (המערכת הזו אינה Windows או Mac)."
        urllib.request.urlretrieve(url, dst)
        if os.name == "nt":
            os.startfile(str(dst))
        else:
            subprocess.run(["open", str(dst)])
        return "המתקין הופעל. אשרו אותו בחלון שנפתח (ייתכן שיידרשו הרשאות מנהל), והתחברו לחשבון Google."
    except Exception as e:
        webbrowser.open(DRIVE_PAGE)
        return f"ההורדה האוטומטית נכשלה ({type(e).__name__}). נפתח דף ההורדה של Google, התקינו משם ידנית."

def drive_box():
    inst = drive_installed()
    with st.expander("גישה לתיקיית Google Drive", expanded=(inst is False)):
        if inst is True:
            st.success("Google Drive for Desktop מותקן. בחרו את התיקייה תחת כונן Drive (בדרך כלל G:).")
        else:
            st.write("התיקייה נמצאת ב-Google Drive. כדי לבחור אותה כאן צריך את Google Drive for Desktop, שמציג את ה-Drive כאות כונן במחשב."
                     + (" לא זיהיתי אותו במחשב הזה (הזיהוי עלול לטעות אם הותקן במקום לא רגיל)." if inst is False else ""))
            st.caption("הכפתור מוריד את המתקין הרשמי של Google ומפעיל אותו. עדיין צריך לאשר את ההתקנה ולהתחבר לחשבון. אם ההתקנה נחסמת, פנו למנהל המחשב.")
            if st.button("התקן Google Drive"):
                st.info(install_drive())
        st.caption("אחרי ההתקנה: אם התיקייה שותפה אליכם, הוסיפו אותה ל-My Drive (קליק ימני ← Organize ← Add shortcut), וסמנו אותה ב-Explorer כ-Available offline כדי שהבדיקה לא תהיה איטית.")

def color(df, col):
    shown = df.copy()
    shown[col] = shown[col].map(lambda v: LABEL.get(v, v))
    inv = {LABEL[k]: v for k, v in COLORS.items()}
    return shown.style.map(lambda v: f"background-color:{inv.get(v,'')}", subset=[col])


st.title("בדיקות לניסוי")
tab_pre, tab_end = st.tabs(["לפני הניסוי (שלב 4)", "סוף ניסוי (שלב 10)"])

with tab_pre:
    st.write("בודק שהמשתתף מילא הסכמה, שאלון דמוגרפי ורישיון, ושיש לו שיבוץ. מריצים כשמתכוננים ליצור קשר לפני הניסוי.")
    st.info("העלו ייצוא Qualtrics (csv או xlsx) של כל טופס. אפשר להעלות רק חלק מהם. העמודות מזוהות אוטומטית, ובדוח כתוב באיזו עמודה נעשה שימוש.")
    asg = st.file_uploader("טבלת שיבוץ (csv או xlsx, עמודות participant ו-test_ID)", type=["csv", "xlsx"], key="p_asg")
    u1 = st.file_uploader("הסכמה מדעת", type=["csv", "xlsx"], key="p_c")
    u2 = st.file_uploader("שאלון דמוגרפי", type=["csv", "xlsx"], key="p_d")
    u3 = st.file_uploader("רישיון נהיגה", type=["csv", "xlsx"], key="p_l")
    only = st.text_input("בדיקה רק למשתתפים אלה (לא חובה, למשל D7,D8). ריק = כל מי שבשיבוץ", key="p_only")
    idcol = st.text_input("שם עמודת מספר המשתתף בטפסים (לא חובה, אם הזיהוי האוטומטי נכשל)", key="p_idcol")
    if st.button("הפעל בדיקה לפני הניסוי", type="primary", disabled=asg is None):
        outdir = Path(tempfile.mkdtemp(prefix="pre_out_"))
        cmd = SELF + ["--before", "--assignment", save_upload(asg, outdir, "assignment"), "--out", str(outdir)]
        for flag, up, nm in (("--consent", u1, "consent"), ("--demographic", u2, "demographic"), ("--license", u3, "license")):
            pth = save_upload(up, outdir, nm)
            if pth: cmd += [flag, pth]
        if only.strip(): cmd += ["--only", only.strip()]
        if idcol.strip(): cmd += ["--id-col", idcol.strip()]
        with st.spinner("בודק…"):
            pr = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        show_report(pr, outdir / "pre_check_report.xlsx", "pre_check_report.xlsx")
        st.caption("הבדיקה לא מחליפה צפייה בסרטון האפוטרופוס ובתמונת הרישיון: היא בודקת רק שהקבצים הועלו.")

with tab_end:
    drive_box()
    st.write("בודק את תיקיות המשתתפים אחרי הניסוי: קובץ תוצאות, קובץ הקלטה (וידאו ואורך), כיסוי ההקלטה את הסקר ותקינות התשובות.")
    if "folder" not in st.session_state:
        st.session_state.folder = ""
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
        folder = st.text_input("תיקיית המשתתפים (אפשר גם להדביק נתיב ידנית)", key="folder")
    if folder:
        p = Path(folder)
        if p.is_dir():
            found = [i.name for i in p.iterdir() if i.suffix.lower() == ".zip" or (i.is_dir() and i.name[:1] in "Dd" and i.name[1:2].isdigit())]
            (st.success if found else st.warning)(f"נמצאו {len(found)} משתתפים: {', '.join(sorted(found)[:6])}{'…' if len(found) > 6 else ''}" if found else "בתיקייה אין קבצי zip או תיקיות של משתתפים (D…).")
        else:
            st.error("התיקייה לא קיימת.")
    up = st.file_uploader("קובץ שיבוץ (לא חובה; csv עם participant ו-test_ID)", type=["csv"], key="e_asg")
    with st.expander("הגדרות מתקדמות (ברירות המחדל מתאימות)"):
        a, b, c = st.columns(3)
        pairs = a.number_input("זוגות צפויים", 1, 50, 8)
        mn = b.number_input("משך מינימלי (דק׳)", 0.0, 500.0, 10.0)
        mx = c.number_input("משך מקסימלי (דק׳)", 0.0, 500.0, 90.0)
        pg = a.number_input("שניות מינימום לעמוד", 0.0, 600.0, 20.0)
        eq = b.number_input("% תשובות ״שווה״ מקסימלי", 0.0, 100.0, 40.0)
        ld = c.number_input("פער הקלטה/שאלון (דק׳)", 0.0, 500.0, 20.0)
    if st.button("הפעל בדיקת סוף ניסוי", type="primary", disabled=not (folder and Path(folder).is_dir())):
        outdir = Path(tempfile.mkdtemp(prefix="chk_out_"))
        cmd = SELF + ["--checker", folder, "--out", str(outdir),
               "--expected-pairs", str(pairs), "--min-minutes", str(mn), "--max-minutes", str(mx),
               "--min-page-seconds", str(pg), "--max-equal-pct", str(eq), "--max-lead-minutes", str(ld)]
        ap = save_upload(up, outdir, "assignment")
        if ap: cmd += ["--assignment", ap]
        with st.spinner("הבדיקה רצה. עם הקלטות גדולות זה יכול לקחת כמה דקות…"):
            pr = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        show_report(pr, outdir / "session_check_report.xlsx", "session_check_report.xlsx")
        st.caption("הבדיקה לא מכסה הסכמה, שאלון דמוגרפי, רישיון ואישור אפוטרופוס: אלה נבדקים בלשונית ״לפני הניסוי״.")
