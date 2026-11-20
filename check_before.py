# -*- coding: utf-8 -*-
"""
בדיקה לפני הניסוי (שלב 4 במצגת): האם המשתתף מילא כראוי הסכמה מדעת, שאלון דמוגרפי ורישיון נהיגה, והאם יש לו שיבוץ.

  python3 check_before.py --assignment assignment.csv --consent consent.csv --demographic demo.csv --license license.csv --out REPORT_DIR
                          [--only D7,D8] [--id-col "מספר משתתף"]

* assignment: csv/xlsx עם העמודות participant ו-test_ID (כמו בבדיקת סוף הניסוי).
* כל אחד מהטפסים הוא ייצוא Qualtrics (csv או xlsx). אפשר לתת רק חלק מהם. הטפסים יכולים להיות גם קובץ אחד.
* העמודות מזוהות לפי מילות מפתח בשם העמודה ובטקסט השאלה. בכל בדיקה מצוין באיזו עמודה נעשה שימוש, כדי שאפשר יהיה לאמת.
  לא ראיתי את הייצוא האמיתי של הטפסים, לכן הזיהוי הוא מיטבי ודורש אימות בהרצה ראשונה.
"""
import argparse, re, sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_sessions import fix_text, style_report, PASS, WARN, FAIL, INFO, ORDER, ID_RE   # noqa: E402

KW = dict(
    id=["מספר משתתף", "קוד משתתף", "מזהה", "participant", "subject", "id"],
    consent=["מסכים", "הסכמ", "consent", "agree"],
    guardian=["אפוטרופוס", "הורה", "guardian", "parent"],
    age=["גיל", "age", "תאריך לידה", "שנת לידה", "birth"],
    license=["רישיון", "רשיון", "license", "licence"],
)
NEG = ["לא מסכים", "אינני מסכים", "do not agree", "disagree", "no"]


def read_export(path):
    """Two layouts: Qualtrics export (3 header rows) or a plain sheet / Google Forms (one header row, then answers)"""
    p = Path(path)
    d = pd.read_csv(p, encoding="utf-8-sig", header=None, dtype=str) if p.suffix.lower() == ".csv" else pd.read_excel(p, header=None, dtype=str)
    d = d.map(fix_text)
    names = [str(c) for c in d.iloc[0]]
    has_import = d.shape[0] > 2 and str(d.iat[2, 0]).startswith('{"ImportId"')
    if has_import:                                   # Qualtrics
        texts, body = [str(c) for c in d.iloc[1]], d.iloc[3:]
        qcols = [i for i in range(len(names)) if "QID" in str(d.iat[2, i])]
    else:                                            # plain sheet: header row, then one row per response
        texts, body = names, d.iloc[1:]
        skip = ("timestamp", "חותמת זמן", "email", "אימייל", "דוא")
        qcols = [i for i, n in enumerate(names) if not any(x in n.lower() for x in skip)]
    body = body.reset_index(drop=True); body.columns = range(len(names))
    return dict(names=names, texts=texts, body=body, qcols=qcols, has_import=has_import, path=p.name)


def has_word(s, w):
    """Hebrew keywords match as substrings; English ones only as whole words (so 'age' does not match 'message')"""
    w = w.lower()
    return bool(re.search(r"\b" + re.escape(w) + r"\b", s)) if w.isascii() else w in s


def find_cols(ex, words, exclude=()):
    out = []
    for i, (n, t) in enumerate(zip(ex["names"], ex["texts"])):
        s = f"{n} {t}".lower()
        if any(has_word(s, w) for w in words) and not any(has_word(s, x) for x in exclude):
            out.append(i)
    return out


def norm(s):
    return re.sub(r"[^0-9a-zא-ת]", "", str(s).lower())


def tokens(pid):
    m = re.match(r"^D(\d+)_(\d+)", pid, re.I)
    t = {norm(pid)}
    if m:
        t |= {norm("D" + m.group(1)), m.group(1), m.group(2)}
    return t


def empty(v):
    return v is None or (isinstance(v, float) and v != v) or str(v).strip() in ("", "nan")


def get_age(text):
    s = str(text)
    m = re.search(r"(\d{4})", s)
    if m and 1900 < int(m.group(1)) < date.today().year + 1 and not re.fullmatch(r"\s*\d{1,3}\s*", s):
        return date.today().year - int(m.group(1))
    m = re.search(r"\d{1,3}", s)
    return int(m.group()) if m else None


def main():
    ap = argparse.ArgumentParser(description="בדיקה לפני הניסוי")
    ap.add_argument("--assignment", required=True)
    ap.add_argument("--consent"); ap.add_argument("--demographic"); ap.add_argument("--license")
    ap.add_argument("--only", help="רשימת משתתפים לבדיקה, מופרדת בפסיקים (ברירת מחדל: כולם)")
    ap.add_argument("--id-col", help="שם עמודת מספר המשתתף בטפסים (אם הזיהוי האוטומטי לא מתאים)")
    ap.add_argument("--out", default="pre_check_out")
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)

    p = Path(a.assignment)
    A = pd.read_csv(p, dtype=str, encoding="utf-8-sig") if p.suffix.lower() == ".csv" else pd.read_excel(p, dtype=str)
    A = A.map(fix_text) if hasattr(A, "map") else A
    if "participant" not in A.columns:
        sys.exit("בקובץ השיבוץ חסרה עמודה בשם participant")
    A["participant"] = A["participant"].astype(str).str.strip()
    A = A[A["participant"].map(lambda s: bool(ID_RE.match(s)))]
    if a.only:
        want = [w.strip() for w in a.only.split(",") if w.strip()]
        A = A[A["participant"].map(lambda s: any(tokens(s) & tokens(w) or norm(w) in tokens(s) for w in want))]
    if A.empty:
        sys.exit("לא נמצאו משתתפים בטבלת השיבוץ (בדקו את שמות העמודות או את רשימת --only)")

    forms = {}
    for key, label in (("consent", "הסכמה"), ("demographic", "שאלון דמוגרפי"), ("license", "רישיון נהיגה")):
        if getattr(a, key):
            forms[key] = (label, read_export(getattr(a, key)))

    def row_of(ex, pid):
        idc = [i for i, n in enumerate(ex["names"]) if a.id_col and n.strip() == a.id_col] or find_cols(ex, KW["id"], exclude=["response id", "responseid", "ip", "recorded", "external"])
        for c in idc:
            hits = ex["body"][ex["body"][c].map(lambda v: norm(v) in tokens(pid) if not empty(v) else False)]
            if len(hits):
                return hits, ex["names"][c]
        return ex["body"].iloc[0:0], (ex["names"][idc[0]] if idc else None)

    results = {}
    codes = A["test_ID"].astype(str).str.strip() if "test_ID" in A.columns else None
    for _, r in A.iterrows():
        pid = r["participant"]; checks = []
        add = lambda n, s, m="": checks.append((n, s, m))
        code = str(r.get("test_ID", "")).strip() if "test_ID" in A.columns else ""
        if not code or code.lower() == "nan":
            add("שיבוץ: קוד בלוק", FAIL, "אין test_ID בטבלת השיבוץ")
        elif not re.fullmatch(r"P\d+", code):
            add("שיבוץ: קוד בלוק", WARN, f"'{code}' אינו בתבנית P<מספר>")
        else:
            dup = [x for x in A[A["test_ID"].astype(str).str.strip() == code]["participant"] if x != pid]
            add("שיבוץ: קוד בלוק", WARN if dup else PASS, f"{code}" + (f", מוקצה גם ל-{', '.join(dup)}" if dup else ""))
        ages, found_rows = [], {}
        for key, (label, ex) in forms.items():
            hits, idname = row_of(ex, pid)
            if idname is None:
                add(f"{label}: זיהוי משתתף", WARN, "לא זוהתה עמודת מספר משתתף בטופס. ציינו --id-col")
                continue
            if hits.empty:
                add(f"{label}: נמצא בטופס", FAIL, f"אין תשובה של {pid} (עמודה: {idname})")
                continue
            if len(hits) > 1:
                add(f"{label}: תשובה יחידה", WARN, f"{len(hits)} תשובות; נבדקה האחרונה")
            row = hits.iloc[-1]; found_rows[key] = (ex, row)
            add(f"{label}: נמצא בטופס", PASS, f"עמודה: {idname}")
            fin = find_cols(ex, ["finished", "הסתיים", "הושלם"], exclude=["progress"])
            if fin:
                v = str(row[fin[0]]).strip().lower()
                add(f"{label}: הושלם", PASS if v in ("true", "1", "1.0", "כן") else FAIL, f"{ex['names'][fin[0]]} = {v}")
            if ex["qcols"]:
                skip = set(find_cols(ex, KW["guardian"] + KW["license"]))      # checked separately below
                miss = [ex["texts"][i][:40] for i in ex["qcols"] if empty(row[i]) and i not in skip]
                add(f"{label}: שאלות ריקות", WARN if miss else PASS,
                    (f"{len(miss)} ריקות, למשל: " + " | ".join(miss[:3])) if miss else "כל השאלות מולאו")
            else:
                add(f"{label}: שאלות ריקות", INFO, "לא נבדק (לא זוהו עמודות שאלות)")
        # consent answer
        if "consent" in found_rows:
            ex, row = found_rows["consent"]
            cc = find_cols(ex, KW["consent"], exclude=["אפוטרופוס", "guardian", "הורה"])
            if not cc:
                add("הסכמה: תשובת ההסכמה", WARN, "לא זוהתה עמודת הסכמה, לבדוק ידנית")
            else:
                vals = [(ex["names"][i], str(row[i])) for i in cc if not empty(row[i])]
                refused = [f"{n} = {v[:30]}" for n, v in vals if any(has_word(v.lower(), x) for x in NEG)]
                if not vals:
                    add("הסכמה: תשובת ההסכמה", FAIL, f"עמודה {ex['names'][cc[0]]} ריקה")
                elif refused:
                    add("הסכמה: תשובת ההסכמה", FAIL, "נראה שלא הסכים: " + ", ".join(refused))
                else:
                    add("הסכמה: תשובת ההסכמה", PASS, f"{vals[0][0]} = {vals[0][1][:40]}")
        # age -> guardian video
        age = None
        for key, (ex, row) in found_rows.items():
            for c in find_cols(ex, KW["age"]):
                if not empty(row[c]):
                    age = get_age(row[c]); break
            if age is not None:
                break
        if "consent" in found_rows:
            ex, row = found_rows["consent"]
            gc = find_cols(ex, KW["guardian"])
            if age is None:
                add("קטין: גיל", WARN, "לא נמצא גיל בטפסים, אי אפשר לדעת אם נדרש אישור אפוטרופוס")
            elif age < 18:
                if not gc:
                    add("קטין: סרטון אפוטרופוס", WARN, f"גיל {age}, אך לא זוהתה עמודת אישור אפוטרופוס. לבדוק ידנית")
                else:
                    ok = any(not empty(row[c]) for c in gc)
                    add("קטין: סרטון אפוטרופוס", PASS if ok else FAIL,
                        f"גיל {age}; " + ("הועלה קובץ (נא לצפות ידנית שהוא תקין)" if ok else "לא הועלה קובץ"))
            else:
                add("קטין: גיל", PASS, f"גיל {age}, לא נדרש אפוטרופוס")
        if "license" in found_rows:
            ex, row = found_rows["license"]
            lc = find_cols(ex, KW["license"])
            if not lc:
                add("רישיון: העלאת תמונה", WARN, "לא זוהתה עמודת רישיון, לבדוק ידנית")
            else:
                ok = any(not empty(row[c]) for c in lc)
                add("רישיון: העלאת תמונה", PASS if ok else FAIL, "הועלה קובץ (נא לוודא ידנית שהתמונה קריאה)" if ok else f"עמודה {ex['names'][lc[0]]} ריקה")
        results[pid] = dict(code=code, checks=checks)

    names = []
    for r in results.values():
        for c in r["checks"]:
            if c[0] not in names:
                names.append(c[0])
    rows, det = [], []
    for pid, r in sorted(results.items()):
        worst = max((c[1] for c in r["checks"]), key=lambda s: ORDER[s], default=PASS)
        by = {c[0]: c for c in r["checks"]}
        rows.append({"משתתף": pid, "test_ID": r["code"], "סטטוס כולל": worst, **{n: by[n][1] if n in by else "" for n in names}})
        det += [{"משתתף": pid, "בדיקה": n, "סטטוס": s, "פירוט": m} for n, s, m in r["checks"]]
    S, D = pd.DataFrame(rows), pd.DataFrame(det)
    D.to_csv(out / "pre_check_details.csv", index=False, encoding="utf-8-sig")
    xlsx = out / "pre_check_report.xlsx"
    with pd.ExcelWriter(xlsx, engine="openpyxl") as xw:
        S.to_excel(xw, sheet_name="סיכום", index=False); D.to_excel(xw, sheet_name="פירוט", index=False)
    style_report(xlsx)
    print(f"\nנבדקו {len(S)} משתתפים. הדוח: {xlsx}\n")
    for _, row in S.iterrows():
        print(f"{row['משתתף']:<14} {row['test_ID']:<6} {row['סטטוס כולל']}")
    bad = D[D["סטטוס"].isin([FAIL, WARN])]
    if len(bad):
        print("\nמה דורש תשומת לב:")
        for _, b in bad.sort_values("סטטוס").iterrows():
            print(f"  [{b['סטטוס']}] {b['משתתף']}: {b['בדיקה']} - {b['פירוט']}")


if __name__ == "__main__":
    main()
