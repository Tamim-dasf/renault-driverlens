import csv
import glob
import hashlib
import html
import os
import re
import unicodedata
import warnings
from collections import Counter
from typing import Dict, List, Optional, Any, Set, Tuple

import pandas as pd

from .helpers import setup_logger

logger = setup_logger(__name__)

# Excel files exported by browser tools often have no default style: harmless warning.
warnings.filterwarnings("ignore", message="Workbook contains no default style")

# ----------------------------------------------------------------------------
# Settings (all can be overridden when calling the functions)
# ----------------------------------------------------------------------------

# Names (after normalization: lowercase, letters and digits only) under which each
# standard column may appear in an exported file.
COLUMN_ALIASES: Dict[str, List[str]] = {
    "comment": ["comment", "comments", "commenttext", "text", "textdisplay", "textoriginal",
                "content", "commentaire", "body", "message", "reviewtext"],
    "author": ["author", "authorname", "authordisplayname", "username", "user", "commenter"],
    "likes": ["likes", "likecount", "like", "votes", "upvotes"],
    "date": ["date", "publishedat", "published", "timestamp", "datetime", "time", "updatedat"],
    "video_title": ["videotitle", "video", "title", "videoname"],
    "car_model": ["carmodel", "model", "car", "vehicle"],
    "id": ["id", "commentid"],
    "reply_to": ["replyto", "parentid", "parent"],
    "is_creator": ["iscreator", "creator", "isauthor"],
}

# Keywords used to recognise the car model in a file name, a video title or the comments.
# Edit freely. Accents and punctuation are ignored ("Mégane" = "megane", "E-Tech" = "e tech").
DEFAULT_CAR_MODEL_KEYWORDS: Dict[str, List[str]] = {
    "Renault 5 E-Tech": ["renault 5", "r5", "5 e-tech", "5 etech"],
    "Mégane E-Tech": ["megane"],
    "Scénic E-Tech": ["scenic"],
    "Renault 4 E-Tech": ["renault 4", "r4", "4 e-tech", "4 etech"],
    "Twingo E-Tech": ["twingo"],
    "Zoé": ["zoe"],
    "Kangoo E-Tech": ["kangoo"],
}

# Minimum number of comments mentioning a model before we trust it as "the model of this file".
MIN_MODEL_MENTIONS = 3

SUPPORTED_EXTENSIONS = (".csv", ".xlsx", ".xlsm")

STANDARD_COLUMNS = ["comment_id", "car_model", "comment", "parent_comment", "author", "likes",
                    "date", "video_title", "source_file"]

RESULT_COLUMNS = ["comment_id", "car_model", "comment", "surface_sentiment", "latent_concern",
                  "hypothesis_type", "hypothesis", "churn_risk", "action", "message",
                  "utility", "revisions_done", "error"]

# ----------------------------------------------------------------------------
# Small text helpers
# ----------------------------------------------------------------------------
_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_URL_RE = re.compile(r"https?://\S+|www\.\S+")
_USER_MENTION_RE = re.compile(r"(?<![\w.+-])@[\w](?:[\w.-]*[\w])?", re.UNICODE)
_INVISIBLE_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060\ufeff]")
_SPACES_RE = re.compile(r"\s+")
_LETTER_RE = re.compile(r"[^\W\d_]", re.UNICODE)


def _norm_text(value: Any) -> str:
    """Lowercase, no accents, separators turned into single spaces."""
    text = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _norm_column(name: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def clean_comment_text(text: Any) -> str:
    """Remove HTML, links and invisible characters; normalize spaces."""
    if not isinstance(text, str):
        return ""
    text = html.unescape(text)
    text = _BR_RE.sub(" ", text)
    text = _TAG_RE.sub("", text)
    text = _URL_RE.sub("", text)
    text = _INVISIBLE_RE.sub("", text)
    return _SPACES_RE.sub(" ", text).strip()


def remove_user_mentions(text: Any) -> str:
    """Remove @handles from analysis text without changing dataset IDs."""
    if not isinstance(text, str):
        return ""
    return _SPACES_RE.sub(" ", _USER_MENTION_RE.sub(" ", text)).strip()


def _keyword_in(haystack: str, keyword: str) -> bool:
    """`haystack` is a normalized text padded with spaces. Short keywords (r5, r4) must be whole words."""
    key = _norm_text(keyword)
    return f" {key} " in haystack or (len(key) > 3 and key in haystack)


def detect_car_model(text: Any, keywords: Optional[Dict[str, List[str]]] = None) -> Optional[str]:
    """Return the first car model whose keyword appears in `text`, or None."""
    keywords = keywords or DEFAULT_CAR_MODEL_KEYWORDS
    haystack = f" {_norm_text(text)} "
    for model, words in keywords.items():
        if any(_keyword_in(haystack, w) for w in words):
            return model
    return None


def _count_model_mentions(texts: List[str], keywords: Optional[Dict[str, List[str]]]) -> Counter:
    """For each car model, the number of comments that mention it."""
    keywords = keywords or DEFAULT_CAR_MODEL_KEYWORDS
    counts: Counter = Counter()
    for text in texts:
        haystack = f" {_norm_text(text)} "
        for model, words in keywords.items():
            if any(_keyword_in(haystack, w) for w in words):
                counts[model] += 1
    return counts


# ----------------------------------------------------------------------------
# Reading one file (.csv or .xlsx)
# ----------------------------------------------------------------------------
def _detect_delimiter(sample: str) -> str:
    """Pick the delimiter that appears most often in the header line."""
    lines = sample.splitlines()
    header = lines[0] if lines else ""
    counts = {d: header.count(d) for d in (",", ";", "\t", "|")}
    best = max(counts, key=counts.get)
    return best if counts[best] > 0 else ","


def _read_csv(path: str) -> pd.DataFrame:
    """Read a CSV whatever its encoding (UTF-8, Windows, Latin-1) and delimiter."""
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            with open(path, "r", encoding=encoding, newline="") as f:
                sep = _detect_delimiter(f.read(20000))
            return pd.read_csv(path, sep=sep, encoding=encoding, dtype=str, on_bad_lines="skip")
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Could not read {path} with any known encoding.")


def _read_excel(path: str) -> pd.DataFrame:
    """Read the 'Comments' sheet if there is one, otherwise the first sheet."""
    sheets = pd.ExcelFile(path).sheet_names
    sheet = "Comments" if "Comments" in sheets else sheets[0]
    return pd.read_excel(path, sheet_name=sheet, dtype=str)


def _read_table(path: str) -> pd.DataFrame:
    if path.lower().endswith((".xlsx", ".xlsm")):
        return _read_excel(path)
    return _read_csv(path)


def _find_columns(columns: List[str], column_map: Optional[Dict[str, str]]) -> Dict[str, Optional[str]]:
    """Map each standard column name to the real column name in the file (or None)."""
    found: Dict[str, Optional[str]] = {}
    by_norm = {_norm_column(c): c for c in columns}
    for standard, aliases in COLUMN_ALIASES.items():
        if column_map and column_map.get(standard) in columns:
            found[standard] = column_map[standard]
            continue
        found[standard] = next((by_norm[a] for a in aliases if a in by_norm), None)
    return found


def _resolve_file_car_model(filename: str, texts: List[str], keywords: Optional[Dict[str, List[str]]],
                            file_car_models: Optional[Dict[str, str]],
                            min_mentions: int) -> Tuple[str, str]:
    """
    Decide which car model a whole file is about. Returns (model, how_we_know).
    Order: your own mapping > file name > most-mentioned model in the comments > unknown.
    """
    if file_car_models and filename in file_car_models:
        return file_car_models[filename], "manual mapping"

    stem = os.path.splitext(filename)[0]
    from_name = detect_car_model(stem, keywords)
    if from_name:
        return from_name, "file name"

    votes = _count_model_mentions(texts, keywords)
    if votes:
        model, n = votes.most_common(1)[0]
        if n >= min_mentions:
            return model, f"mentioned in {n}/{len(texts)} comments"

    return f"Unknown ({stem})", "not found: add it to file_car_models"


def _standardize_file(path: str, column_map: Optional[Dict[str, str]],
                      keywords: Optional[Dict[str, List[str]]],
                      file_car_models: Optional[Dict[str, str]],
                      drop_creator: bool, min_mentions: int) -> pd.DataFrame:
    """Load one file and return it with the standard columns."""
    raw = _read_table(path)
    columns = list(raw.columns)
    found = _find_columns(columns, column_map)
    filename = os.path.basename(path)

    if not found["comment"]:
        if len(columns) == 1:
            found["comment"] = columns[0]
        else:
            raise ValueError(
                f"{filename}: cannot tell which column holds the comment text. "
                f"Columns found: {columns}. Pass column_map={{'comment': '<column name>'}}."
            )

    def pick(name: str) -> pd.Series:
        col = found[name]
        return raw[col] if col else pd.Series([None] * len(raw), index=raw.index)

    texts = raw[found["comment"]].map(clean_comment_text)

    # Replies: attach the text of the comment they answer (same file, same id numbering).
    parent = pd.Series([""] * len(raw), index=raw.index)
    if found["id"] and found["reply_to"]:
        text_by_id = dict(zip(raw[found["id"]], texts))
        parent = raw[found["reply_to"]].map(
            lambda r: text_by_id.get(r, "")[:300] if isinstance(r, str) and r.strip() not in ("", "0") else ""
        )

    df = pd.DataFrame({
        "car_model": pick("car_model"),
        "comment": texts,
        "parent_comment": parent,
        "author": pick("author"),
        "likes": pd.to_numeric(pick("likes"), errors="coerce"),
        "date": pick("date"),
        "video_title": pick("video_title"),
        "source_file": filename,
    })

    # The video creator is not a customer: drop their own comments.
    if drop_creator and found["is_creator"]:
        is_creator = raw[found["is_creator"]].fillna("").str.strip().str.lower().isin(["true", "1", "yes"])
        df = df[~is_creator]

    # Car model: your manual mapping > a car_model column > video title > the file as a whole.
    file_model, how = _resolve_file_car_model(filename, [t for t in df["comment"] if t], keywords,
                                              file_car_models, min_mentions)
    if how == "manual mapping":
        df["car_model"] = file_model
    else:
        model = df["car_model"].fillna("").astype(str).str.strip()
        from_title = df["video_title"].fillna("").map(lambda t: detect_car_model(t, keywords) or "")
        model = model.where(model != "", from_title)
        df["car_model"] = model.where(model != "", file_model)

    logger.info(f"{filename}: {len(df)} rows, car model = {file_model} ({how})")
    return df


# ----------------------------------------------------------------------------
# Public functions
# ----------------------------------------------------------------------------
def load_comments(data_dir: str, column_map: Optional[Dict[str, str]] = None,
                  car_model_keywords: Optional[Dict[str, List[str]]] = None,
                  file_car_models: Optional[Dict[str, str]] = None,
                  drop_creator: bool = True, min_chars: int = 8, max_chars: int = 1000,
                  min_model_mentions: int = MIN_MODEL_MENTIONS) -> pd.DataFrame:
    """
    Load, clean and merge every .csv / .xlsx file found in `data_dir` (subfolders included).

    Args:
        data_dir: folder with the exported files.
        column_map: force a column, e.g. {"comment": "Texte"}.
        car_model_keywords: replaces DEFAULT_CAR_MODEL_KEYWORDS.
        file_car_models: tell us the model of a file, e.g.
            {"yt-comments-2026-11-13-11-52-32.xlsx": "Scénic E-Tech"}. Always wins.
        drop_creator: remove comments written by the video creator.

    Cleaning: HTML and links removed, empty / very short / emoji-only comments dropped,
    duplicates dropped (same car model + same text), long comments truncated.

    Returns a DataFrame with the columns of STANDARD_COLUMNS. `comment_id` is a hash of
    the car model and the text, so it stays the same between runs (needed to resume).
    """
    paths = sorted(
        p for p in glob.glob(os.path.join(data_dir, "**", "*"), recursive=True)
        if p.lower().endswith(SUPPORTED_EXTENSIONS) and not os.path.basename(p).startswith("~$")
    )
    if not paths:
        raise FileNotFoundError(f"No .csv or .xlsx file found in '{data_dir}'.")

    frames = [_standardize_file(p, column_map, car_model_keywords, file_car_models,
                                drop_creator, min_model_mentions) for p in paths]
    data = pd.concat(frames, ignore_index=True)
    total = len(data)

    has_letters = data["comment"].map(lambda t: bool(_LETTER_RE.search(t)))
    data = data[(data["comment"].str.len() >= min_chars) & has_letters]
    after_filter = len(data)

    dedup_key = data["car_model"].str.lower() + "|" + data["comment"].str.lower()
    data = data[~dedup_key.duplicated()].copy()
    data["comment"] = data["comment"].str.slice(0, max_chars)

    data["comment_id"] = [
        hashlib.sha1(f"{m}|{c}".encode("utf-8")).hexdigest()[:10]
        for m, c in zip(data["car_model"], data["comment"])
    ]
    data = data[STANDARD_COLUMNS].reset_index(drop=True)

    logger.info(f"{len(paths)} file(s), {total} rows read, {total - after_filter} removed "
                f"(empty/short/emoji-only), {after_filter - len(data)} duplicates removed "
                f"-> {len(data)} comments kept.")
    return data


def describe_data(df: pd.DataFrame) -> None:
    """Print a short overview: comments per car model and comment length."""
    print(f"\n{len(df)} comments in total")
    print(df["car_model"].value_counts().to_string())
    lengths = df["comment"].str.len()
    print(f"Comment length: median {int(lengths.median())} chars, max {int(lengths.max())} chars\n")


def sample_comments(df: pd.DataFrame, n: Optional[int], seed: int = 42,
                    by: str = "car_model") -> pd.DataFrame:
    """
    Take a sample of n comments with every car model represented (as evenly as the data
    allows). Useful to stay inside the free-tier limits. n=None returns everything.
    """
    if n is None or n >= len(df):
        return df.reset_index(drop=True)

    groups = [g for _, g in df.groupby(by)]
    per_group = -(-n // len(groups))  # ceiling division
    sample = pd.concat([g.sample(min(len(g), per_group), random_state=seed) for g in groups])

    if len(sample) > n:
        sample = sample.sample(n, random_state=seed)
    elif len(sample) < n:  # small groups: top up with random leftovers
        leftovers = df.drop(sample.index)
        sample = pd.concat([sample, leftovers.sample(min(n - len(sample), len(leftovers)),
                                                     random_state=seed)])
    return sample.reset_index(drop=True)


# ----------------------------------------------------------------------------
# Saving results (one row written as soon as a comment is processed)
# ----------------------------------------------------------------------------
def build_result_row(item: Dict[str, Any], selected_hypothesis: Optional[Dict[str, Any]] = None,
                     response_result: Optional[Dict[str, Any]] = None, error: str = "") -> Dict[str, Any]:
    """Flatten the pipeline output of one comment into one row of the results table."""
    hyp = selected_hypothesis or {}
    res = response_result or {}
    validation = res.get("validation", {})
    return {
        "comment_id": item.get("comment_id"),
        "car_model": item.get("car_model"),
        "comment": item.get("comment"),
        "surface_sentiment": hyp.get("surface_sentiment", ""),
        "latent_concern": hyp.get("latent_concern", ""),
        "hypothesis_type": hyp.get("type", ""),
        "hypothesis": hyp.get("explanation", ""),
        "churn_risk": res.get("churn_risk", ""),
        "action": res.get("action", ""),
        "message": res.get("message", ""),
        "utility": round(validation["utility"], 3) if "utility" in validation else "",
        "revisions_done": res.get("revisions_done", ""),
        "error": error,
    }


def append_result(path: str, row: Dict[str, Any]) -> None:
    """Append one row to the results CSV (created with a header if needed).
    Written immediately, so nothing is lost if the run stops."""
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    is_new = not os.path.exists(path)
    # utf-8-sig on creation makes Excel display French accents correctly.
    with open(path, "a", encoding="utf-8-sig" if is_new else "utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=RESULT_COLUMNS, extrasaction="ignore")
        if is_new:
            writer.writeheader()
        writer.writerow(row)


def load_done_ids(path: str) -> Set[str]:
    """IDs already processed successfully (rows with an error are retried)."""
    if not os.path.exists(path):
        return set()
    done = pd.read_csv(path, dtype=str, encoding="utf-8-sig")
    done = done[done["error"].fillna("") == ""]
    return set(done["comment_id"].dropna())
