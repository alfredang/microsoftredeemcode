"""Shared file paths."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)

STORAGE_STATE = DATA / "storage_state.json"
CODES_CSV = DATA / "codes.csv"
DEBUG_DIR = DATA / "debug"
DEBUG_DIR.mkdir(exist_ok=True)
COURSES_JSON = ROOT / "courses.json"

SG_SUFFIX = "?WT.mc_id=ilt_partner_webpage_wwl&ocid=5238477"
