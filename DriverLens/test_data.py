"""
Test script: loads every file of the 'our data' folder and shows what the loader understood.
Place it in 'real project' (next to the 'our data' folder) and run it with the
"Run Python File" button of VS Code (the triangle at the top right).
"""
import os

from utils import load_comments, describe_data

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "our data")

# If the log below says a file's car model is wrong or "Unknown", tell us here, e.g.:
#   "yt-comments-2026-11-13-11-52-32.xlsx": "Scénic E-Tech",
FILE_CAR_MODELS = {
}

df = load_comments(DATA_DIR, file_car_models=FILE_CAR_MODELS)

describe_data(df)
print(df[["car_model", "comment"]].head(10).to_string(max_colwidth=70))