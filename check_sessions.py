#!/usr/bin/env python3
"""
check_sessions.py - automatic end-of-experiment check (replaces step 22, "check list of the end of an experiment").

For every participant it reads
  * the Qualtrics results file (xlsx or csv)  - the answers and the survey timing
  * the Zoom recording(s)                      - length and start time
and writes a green / yellow / red table, one row per participant.

Input: one folder that contains, for every participant, EITHER the zip as downloaded from Drive
(e.g. D5_034599-2026...zip) OR an already extracted folder named like D5_034599.

Usage
  python3 check_sessions.py INPUT_DIR --out REPORT_DIR
  python3 check_sessions.py INPUT_DIR --out REPORT_DIR --assignment assignment.csv --expected-pairs 8

assignment.csv (optional) needs two columns:  participant , test_ID
  participant = the participant folder id, either "D5" or "D5_034599"
  test_ID     = the block code this participant is supposed to get, e.g. "P2"

What is NOT checked yet (those files were not part of the data I saw): informed consent, demographic
questionnaire, driver's-license upload, guardian video for minors. See CHECK_MORE at the bottom to add them.
Needs: pandas, openpyxl, and ffprobe (part of ffmpeg) for the recordings.
"""
import argparse, re, shutil, subprocess, sys, tempfile, zipfile, json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

# ---------------------------------------------------------------- settings (also available as command-line options)
VALID_VALUES = set(range(-9, -1)) | set(range(1, 10))        # the 17-position slider: -9..-2 and 1..9 (1 = equal)
ID_RE = re.compile(r"^(D\d+_\d{6})")                            # participant folder name, e.g. D7_424352
CODE_RE = re.compile(r"^P\d+$")                                 # block code typed at the start of the survey, e.g. P28
ZOOM_RE = re.compile(r"GMT(\d{8})-(\d{6})")                     # Zoom file name: GMT20261115-115249_Recording...
VIDEO_EXT = {".mp4", ".mov", ".mkv"}
AUDIO_EXT = {".m4a", ".mp3", ".wav"}

PASS, WARN, FAIL, INFO = "PASS", "WARN", "FAIL", "INFO"
ORDER = {PASS: 0, INFO: 0, WARN: 1, FAIL: 2}


# ---------------------------------------------------------------- reading helpers
def fix_text(s):
    """Qualtrics xlsx exports turn Hebrew into 'mojibake' (UTF-8 read as latin-1, byte A0 lost). Undo it."""
    if not isinstance(s, str):
        return s
    t = re.sub(r"_x([0-9A-Fa-f]{4})_", lambda m: chr(int(m.group(1), 16)), s)
    try:
        return t.encode("latin-1").replace(b"\xd7 ", b"\xd7\xa0").decode("utf-8", errors="replace")
    except Exception:
        return t


def is_null(v):
    return v is None or (isinstance(v, float) and v != v) or (isinstance(v, str) and v.strip() in ("", "nan"))


def safe_extract(zip_path, dest):
    dest.mkdir(parents=True, exist_ok=True)
    root = dest.resolve()
    with zipfile.ZipFile(zip_path) as z:
        for m in z.infolist():
            target = (dest / m.filename).resolve()
            if root not in target.parents and target != root:
                raise ValueError(f"unsafe path in zip: {m.filename}")
        z.extractall(dest)


def discover(inp, work):
    """participant id -> list of folders holding their files"""
    groups = {}
    for p in sorted(Path(inp).iterdir()):
        if p.name.startswith("."):
            continue
        m = ID_RE.match(p.name)
        gid = m.group(1) if m else p.stem
        if p.suffix.lower() == ".zip":
            dest = work / gid
            safe_extract(p, dest)
            groups.setdefault(gid, []).append(dest)
        elif p.is_dir():
            groups.setdefault(gid, []).append(p)
    return groups


def list_files(dirs):
    return [f for d in dirs for f in Path(d).rglob("*") if f.is_file() and not f.name.startswith(".") and "__MACOSX" not in f.parts]


# ---------------------------------------------------------------- Qualtrics file
def read_qualtrics(path):
    if path.suffix.lower() == ".csv":
        d = pd.read_csv(path, encoding="utf-8-sig", header=None, dtype=str)
    else:
        d = pd.read_excel(path, header=None, dtype=str)
    d = d.map(fix_text)
    start = 3 if str(d.iat[2, 0]).startswith('{"ImportId"') else 2
    cols = [str(c) for c in d.iloc[0]]
    return d, cols, start


def parse_pages(cols):
    """Split the survey columns into pages. First page = items before the first timing block;
    then every page has 4 timing columns (First Click, Last Click, Page Submit, Click Count) followed by its items."""
    t = cols.index("test_ID")
    j, items, pages = t + 1, [], []
    while j < len(cols) and not cols[j].endswith("First Click"):
        items.append(j); j += 1
    if items:
        pages.append(dict(page=cols[items[0]].split("_")[0], items=items, tim=None))
    while j < len(cols):
        if cols[j].endswith("First Click"):
            q, tim, k, items = cols[j].split("_")[0], list(range(j, min(j + 4, len(cols)))), j + 4, []
            while k < len(cols) and not cols[k].endswith("First Click") and cols[k].endswith("_1"):
                items.append(k); k += 1
            pages.append(dict(page=q, items=items, tim=tim)); j = k
        else:
            j += 1
    return pages


def to_float(v):
    try:
        return float(v)
    except Exception:
        return None


def analyse_survey(path, tz, args):
    """returns (facts, checks) for the Qualtrics file"""
    checks, facts = [], {}
    add = lambda name, status, msg="": checks.append((name, status, msg))
    try:
        d, cols, start = read_qualtrics(path)
    except Exception as e:
        add("קריאת קובץ התוצאות", FAIL, f"לא ניתן לקרוא את הקובץ: {e}")
        return facts, checks
    data = d.iloc[start:]
    if len(data) == 0:
        add("קריאת קובץ התוצאות", FAIL, "אין שורת תגובה בקובץ")
        return facts, checks
    if len(data) > 1:
        add("מספר תגובות בקובץ", WARN, f"יש {len(data)} תגובות בקובץ. נבדקה הראשונה.")
    r = data.iloc[0]
    col = {}
    for i, c in enumerate(cols):
        col.setdefault(c, i)                       # first occurrence wins (a later column can have the same name)
    g = lambda name: r.iat[col[name]] if name in col else None

    # --- finished?
    prog, fin, status = to_float(g("Progress")), str(g("Finished")).strip().lower(), g("Status")
    if prog == 100 and fin == "true":
        add("סיום הסקר", PASS, "הסקר הושלם (100%)")
    else:
        add("סיום הסקר", FAIL, f"הסקר לא הושלם: התקדמות {g('Progress')}, Finished={g('Finished')}")
    if str(status).strip() == "Survey Preview":
        add("תגובת בדיקה", FAIL, "התגובה היא Survey Preview ולא תגובה אמיתית")

    # --- code
    code = g("test_ID")
    code = None if is_null(code) else str(code).strip()
    facts["test_ID"] = code
    if code is None:
        add("קוד משתתף (test_ID)", FAIL, "לא הוזן קוד")
    elif not CODE_RE.match(code):
        add("קוד משתתף (test_ID)", WARN, f"הקוד '{code}' לא בתבנית P<מספר>")
    else:
        add("קוד משתתף (test_ID)", PASS, code)

    # --- times
    try:
        s_start = datetime.strptime(g("StartDate"), "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz)
        s_end = datetime.strptime(g("EndDate"), "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz)
        facts["start"], facts["end"] = s_start, s_end
    except Exception:
        s_start = s_end = None
    dur = to_float(g("Duration (in seconds)"))
    facts["duration_min"] = None if dur is None else dur / 60
    if dur is None:
        add("משך הניסוי", WARN, "אין נתון משך")
    elif not (args.min_minutes * 60 <= dur <= args.max_minutes * 60):
        add("משך הניסוי", WARN, f"{dur/60:.1f} דקות, מחוץ לטווח {args.min_minutes}-{args.max_minutes}")
    else:
        add("משך הניסוי", PASS, f"{dur/60:.1f} דקות")

    # --- pages
    pages = parse_pages(cols)
    answered, problems, page_secs, vals_all = [], [], [], []
    for p in pages:
        raw = [r.iat[c] for c in p["items"]]
        if not p["items"] or all(is_null(v) for v in raw):
            continue
        answered.append(p)
        miss = sum(is_null(v) for v in raw)
        if miss:
            problems.append(f"{p['page']}: {miss} פריטים ריקים")
        for v in raw:
            if is_null(v):
                continue
            try:
                iv = int(float(v))
            except Exception:
                problems.append(f"{p['page']}: ערך לא מספרי '{v}'"); continue
            if iv not in VALID_VALUES:
                problems.append(f"{p['page']}: ערך לא חוקי {iv}")
            elif p["tim"] is not None:
                vals_all.append(iv)
        if p["tim"] is not None:
            sec = to_float(r.iat[p["tim"][2]])
            if sec is not None:
                page_secs.append((p["page"], sec))
    pairs = [p for p in answered if p["tim"] is not None]
    first_page = [p for p in answered if p["tim"] is None]
    facts["pair_pages"] = [p["page"] for p in pairs]
    n = len(pairs)
    if n == args.expected_pairs:
        add("מספר זוגות שנענו", PASS, f"{n} זוגות")
    elif n < args.expected_pairs:
        add("מספר זוגות שנענו", FAIL, f"נענו {n} זוגות, צפוי {args.expected_pairs}")
    else:
        add("מספר זוגות שנענו", WARN, f"נענו {n} זוגות, צפוי {args.expected_pairs} (אולי גרסה אחרת של הסקר)")
    add("עמוד ראשון (אימון)", PASS if first_page else WARN, "נענה" if first_page else "העמוד הראשון לא נענה")
    add("פריטים חסרים וערכים לא חוקיים", FAIL if problems else PASS,
        "; ".join(problems[:6]) + (" ..." if len(problems) > 6 else "") if problems else "כל הפריטים נענו בערכים חוקיים")

    if page_secs:
        fast = [f"{q} ({s:.0f} שנ')" for q, s in page_secs if s < args.min_page_seconds]
        add("זמן בעמוד", WARN if fast else PASS,
            ("עמודים מהירים מדי: " + ", ".join(fast)) if fast else f"הקצר ביותר {min(s for _, s in page_secs):.0f} שנ'")
    if vals_all:
        pct = 100 * sum(v == 1 for v in vals_all) / len(vals_all)
        facts["pct_equal"] = pct
        add("אחוז תשובות 'שווה'", WARN if pct > args.max_equal_pct else PASS, f"{pct:.1f}% מהפריטים")
    return facts, checks


# ---------------------------------------------------------------- recordings
def probe(path):
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
                             capture_output=True, text=True, timeout=120).stdout
        j = json.loads(out)
        dur = float(j["format"]["duration"])
        created = j["format"].get("tags", {}).get("creation_time")
        has_video = any(s.get("codec_type") == "video" for s in j.get("streams", []))
        return dict(length_s=dur, created_utc=created, has_video=has_video)
    except Exception:
        return None


def recording_start_utc(path, info):
    m = ZOOM_RE.search(path.name)
    if m:
        return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    if info and info.get("created_utc"):
        try:
            return datetime.fromisoformat(info["created_utc"].replace("Z", "+00:00"))
        except Exception:
            return None
    return None


def analyse_recordings(files, survey_facts, tz, args):
    checks = []
    add = lambda name, status, msg="": checks.append((name, status, msg))
    recs = [f for f in files if f.suffix.lower() in VIDEO_EXT | AUDIO_EXT]
    if not recs:
        add("קובץ הקלטה", FAIL, "לא נמצאה הקלטה")
        return checks
    if shutil.which("ffprobe") is None:
        add("קובץ הקלטה", WARN, f"נמצאו {len(recs)} קבצים אך ffprobe לא מותקן, האורך לא נבדק")
        return checks
    infos = {f: probe(f) for f in recs}
    bad = [f.name for f, i in infos.items() if i is None]
    good = {f: i for f, i in infos.items() if i}
    if not good:
        add("קובץ הקלטה", FAIL, "הקלטות לא קריאות: " + ", ".join(bad))
        return checks
    add("קובץ הקלטה", WARN if bad else PASS,
        f"{len(good)} קבצים" + (f", לא קריאים: {', '.join(bad)}" if bad else ""))
    if not any(i["has_video"] for i in good.values()):
        add("וידאו בהקלטה", WARN, "יש רק אודיו, אין וידאו")
    else:
        kinds = sorted({("gallery" if "gallery" in f.name else "gvo" if "gvo" in f.name else "וידאו") for f, i in good.items() if i["has_video"]})
        add("וידאו בהקלטה", INFO, "תצוגות: " + ", ".join(kinds))
    if not any(ZOOM_RE.search(f.name) for f in good):
        add("שם קובץ הקלטה", INFO, "השם אינו בתבנית Zoom הרגילה (GMT...), ייתכן ששונה ידנית")

    # coverage of the survey: use the longest video (or audio) recording
    main = max(good, key=lambda f: good[f]["length_s"])
    info = good[main]
    rs = recording_start_utc(main, info)
    ss, se = survey_facts.get("start"), survey_facts.get("end")
    if rs is None or ss is None or se is None:
        add("כיסוי ההקלטה את הסקר", WARN, "אין זמן התחלה להקלטה או לסקר, הכיסוי לא נבדק")
        return checks
    rs_local = rs.astimezone(tz)
    re_local = rs_local + timedelta(seconds=info["length_s"])
    lead = (ss - rs_local).total_seconds() / 60          # minutes the recording started before the survey
    tail = (re_local - se).total_seconds() / 60          # minutes the recording ran after the survey ended
    msg = f"ההקלטה התחילה {lead:.1f} דק' לפני הסקר ונגמרה {tail:.1f} דק' אחריו"
    if lead < 0 or tail < 0:
        add("כיסוי ההקלטה את הסקר", FAIL, msg + " - חלק מהסקר לא מוקלט")
    elif lead > args.max_lead_minutes:
        add("כיסוי ההקלטה את הסקר", WARN, msg + f" - התחילה יותר מ-{args.max_lead_minutes} דק' לפני")
    else:
        add("כיסוי ההקלטה את הסקר", PASS, msg)
    return checks


def minority(counter, value):
    """True if the group is not uniform and `value` is not the single most common one (a tie flags everybody)"""
    if len(counter) <= 1:
        return False
    top = max(counter.values())
    return not (counter[value] == top and list(counter.values()).count(top) == 1)


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="Automatic end-of-experiment check")
    ap.add_argument("input", help="folder with the participants' zips / folders")
    ap.add_argument("--out", default="session_check_out", help="report folder")
    ap.add_argument("--assignment", help="csv with columns: participant, test_ID")
    ap.add_argument("--expected-pairs", type=int, default=8)
    ap.add_argument("--tz", default="Asia/Jerusalem", help="time zone of the Qualtrics export")
    ap.add_argument("--min-minutes", type=float, default=10)
    ap.add_argument("--max-minutes", type=float, default=90)
    ap.add_argument("--min-page-seconds", type=float, default=20)
    ap.add_argument("--max-equal-pct", type=float, default=40)
    ap.add_argument("--max-lead-minutes", type=float, default=20)
    ap.add_argument("--fail-on-error", action="store_true", help="exit code 1 if any participant has a FAIL")
    args = ap.parse_args()
    tz = ZoneInfo(args.tz)
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)

    assign = {}
    if args.assignment:
        a = pd.read_csv(args.assignment, dtype=str, encoding="utf-8-sig")
        for _, row in a.iterrows():
            assign[str(row["participant"]).strip().split("_")[0]] = str(row["test_ID"]).strip()

    results = {}                                   # participant -> dict(checks=[...], facts={...})
    with tempfile.TemporaryDirectory() as tmp:
        groups = discover(args.input, Path(tmp))
        if not groups:
            sys.exit(f"לא נמצאו תיקיות או קבצי zip של משתתפים ב-{args.input}")
        for gid, dirs in groups.items():
            files = list_files(dirs)
            checks = []
            add = lambda name, status, msg="": checks.append((name, status, msg))
            add("שם תיקיית משתתף", PASS if ID_RE.match(gid) else WARN,
                gid if ID_RE.match(gid) else f"'{gid}' אינו בתבנית D<מספר>_<6 ספרות>")
            res = [f for f in files if "results" in f.name.lower() and f.suffix.lower() in (".xlsx", ".csv")]
            facts = {}
            if not res:
                add("קובץ תוצאות", FAIL, "לא נמצא קובץ תוצאות (results)")
            else:
                if len(res) > 1:
                    add("קובץ תוצאות", WARN, f"נמצאו {len(res)} קבצים: " + ", ".join(f.name for f in res) + ". נבדק הראשון.")
                else:
                    add("קובץ תוצאות", PASS, res[0].name)
                facts["format"] = res[0].suffix.lower()
                f2, c2 = analyse_survey(res[0], tz, args)
                facts.update(f2); checks += c2
            checks += analyse_recordings(files, facts, tz, args)
            results[gid] = dict(checks=checks, facts=facts)

    # ---- checks across participants
    codes = Counter(r["facts"].get("test_ID") for r in results.values() if r["facts"].get("test_ID"))
    fmts = Counter(r["facts"].get("format") for r in results.values() if r["facts"].get("format"))
    npairs = Counter(len(r["facts"].get("pair_pages", [])) for r in results.values())
    for gid, r in results.items():
        code = r["facts"].get("test_ID")
        if code:
            if codes[code] > 1:
                others = [g for g, x in results.items() if x["facts"].get("test_ID") == code and g != gid]
                r["checks"].append(("קוד ייחודי", FAIL, f"הקוד {code} הוזן גם אצל: {', '.join(others)}"))
            else:
                r["checks"].append(("קוד ייחודי", PASS, "הקוד לא חוזר"))
        if args.assignment:
            exp = assign.get(gid.split("_")[0])
            if exp is None:
                r["checks"].append(("התאמה לטבלת שיבוץ", WARN, "המשתתף לא מופיע בטבלת השיבוץ"))
            elif code is None:
                r["checks"].append(("התאמה לטבלת שיבוץ", FAIL, f"אמור לקבל {exp}, לא הוזן קוד"))
            elif code != exp:
                r["checks"].append(("התאמה לטבלת שיבוץ", FAIL, f"אמור לקבל {exp}, הוזן {code}"))
            else:
                r["checks"].append(("התאמה לטבלת שיבוץ", PASS, f"{code} כמו בשיבוץ"))
        if r["facts"].get("format"):
            if minority(fmts, r["facts"]["format"]):
                r["checks"].append(("פורמט קובץ תוצאות אחיד", WARN, f"{r['facts']['format']}; בקבוצה: {dict(fmts)}"))
            else:
                r["checks"].append(("פורמט קובץ תוצאות אחיד", PASS, r["facts"]["format"]))
        k = len(r["facts"].get("pair_pages", []))
        if minority(npairs, k):
            r["checks"].append(("מספר זוגות אחיד בין משתתפים", WARN, f"{k} זוגות; בקבוצה: {dict(npairs)}"))
        else:
            r["checks"].append(("מספר זוגות אחיד בין משתתפים", PASS, f"{k} זוגות"))

    # ---- report
    names = []
    for r in results.values():
        for c in r["checks"]:
            if c[0] not in names:
                names.append(c[0])
    rows, det = [], []
    for gid, r in sorted(results.items()):
        worst = max((c[1] for c in r["checks"]), key=lambda s: ORDER[s], default=PASS)
        row = {"משתתף": gid, "test_ID": r["facts"].get("test_ID") or "", "סטטוס כולל": worst}
        by = {c[0]: c for c in r["checks"]}
        for n in names:
            row[n] = by[n][1] if n in by else ""
        rows.append(row)
        for n, s, m in r["checks"]:
            det.append({"משתתף": gid, "בדיקה": n, "סטטוס": s, "פירוט": m})
    S, D = pd.DataFrame(rows), pd.DataFrame(det)
    D.to_csv(out / "session_check_details.csv", index=False, encoding="utf-8-sig")
    xlsx = out / "session_check_report.xlsx"
    with pd.ExcelWriter(xlsx, engine="openpyxl") as xw:
        S.to_excel(xw, sheet_name="סיכום", index=False)
        D.to_excel(xw, sheet_name="פירוט", index=False)
    style_report(xlsx)

    # ---- console
    print(f"\nנבדקו {len(results)} משתתפים. הדוח: {xlsx}\n")
    for _, row in S.iterrows():
        print(f"{row['משתתף']:<12} {row['test_ID']:<6} {row['סטטוס כולל']}")
    bad = D[D["סטטוס"].isin([FAIL, WARN])]
    if len(bad):
        print("\nמה דורש תשומת לב:")
        for _, b in bad.sort_values(["סטטוס", "משתתף"], ascending=[True, True]).iterrows():
            print(f"  [{b['סטטוס']}] {b['משתתף']}: {b['בדיקה']} - {b['פירוט']}")
    if args.fail_on_error and (S["סטטוס כולל"] == FAIL).any():
        sys.exit(1)


def style_report(path):
    from openpyxl import load_workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    fills = {PASS: "C6EFCE", WARN: "FFEB9C", FAIL: "FFC7CE", INFO: "E7E6E6"}
    wb = load_workbook(path)
    for ws in wb:
        ws.sheet_view.rightToLeft = True
        for row in ws.iter_rows():
            for c in row:
                c.font = Font(name="Arial", size=10)
                if c.value in fills:
                    c.fill = PatternFill("solid", fgColor=fills[c.value]); c.alignment = Alignment(horizontal="center")
        for c in ws[1]:
            c.font = Font(name="Arial", size=10, bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", fgColor="305496")
            c.alignment = Alignment(wrap_text=True, horizontal="center", vertical="center")
        ws.freeze_panes = "B2"
        for i, col in enumerate(ws.columns, 1):
            w = max((len(str(c.value)) for c in col if c.value is not None), default=8)
            ws.column_dimensions[get_column_letter(i)].width = min(max(10, w + 2), 70 if ws.title == "פירוט" else 22)
        ws.row_dimensions[1].height = 48 if ws.title == "סיכום" else 20
    wb.save(path)


# CHECK_MORE: to add consent / demographic / license checks, read their Qualtrics exports the same way
# (read_qualtrics), look the participant up by the code or ID, and append (name, status, message) tuples to
# that participant's checks list inside main().

if __name__ == "__main__":
    main()
