"""
Default A Level subject weighting profiles.
Each profile maps component names to default weights (summing to 1.0).
Components reference GCSE subject columns or special keys:
  'overall_mean'   -> student's mean GCSE grade
  'best_humanities'-> highest of {History, Geography, Classical Civilisation, RPE}
  'best_science'   -> highest of {Biology, Chemistry, Physics} or DS average
"""

# ---------------------------------------------------------------------------
# Component key constants used in profiles
# ---------------------------------------------------------------------------
OVERALL_MEAN = "overall_mean"
BEST_HUMANITIES = "best_humanities"
BEST_SCIENCE = "best_science"

# GCSE subject column names (after title-case normalisation)
G_ART = "Art"
G_BIOLOGY = "Biology"
G_CHEMISTRY = "Chemistry"
G_CLASSICS = "Classical Civilisation"
G_COMPUTING = "Computing"
G_DT = "Design Technology"
G_DRAMA = "Drama"
G_ECONOMICS = "Economics"
G_ENG_LANG = "English Language"
G_ENG_LIT = "English Literature"
G_FRENCH = "French"
G_FURTHER_MATHS = "Further Mathematics"
G_GEOGRAPHY = "Geography"
G_GERMAN = "German"
G_HISTORY = "History"
G_LATIN = "Latin"
G_MATHS = "Mathematics"
G_MUSIC = "Music"
G_PE = "Physical Education"
G_PHYSICS = "Physics"
G_RPE = "Religion Philosophy And Ethics"
G_SPANISH = "Spanish"
G_DS1 = "Double Science 1"
G_DS2 = "Double Science 2"

# ---------------------------------------------------------------------------
# Profile structure:
#   "primary": {component: weight} - used when primary GCSE is available
#   "fallback": {component: weight} - used when primary GCSE is missing
#   "primary_gcse": the GCSE subject name that determines primary vs fallback
# ---------------------------------------------------------------------------

DEFAULT_PROFILES: dict[str, dict] = {
    "Art": {
        "primary_gcse": G_ART,
        "primary": {G_ART: 0.70, OVERALL_MEAN: 0.30},
        "fallback": {OVERALL_MEAN: 1.00},
    },
    "Biology": {
        "primary_gcse": G_BIOLOGY,
        "primary": {G_BIOLOGY: 0.60, G_MATHS: 0.20, OVERALL_MEAN: 0.20},
        "fallback": {OVERALL_MEAN: 0.60, G_MATHS: 0.40},
    },
    "Business": {
        "primary_gcse": None,
        "primary": {G_MATHS: 0.50, G_ENG_LANG: 0.30, OVERALL_MEAN: 0.20},
        "fallback": {G_MATHS: 0.50, G_ENG_LANG: 0.30, OVERALL_MEAN: 0.20},
    },
    "Chemistry": {
        "primary_gcse": G_CHEMISTRY,
        "primary": {G_CHEMISTRY: 0.60, G_MATHS: 0.20, OVERALL_MEAN: 0.20},
        "fallback": {OVERALL_MEAN: 0.60, G_MATHS: 0.40},
    },
    "Classical Civilisation": {
        "primary_gcse": G_CLASSICS,
        "primary": {G_CLASSICS: 0.70, OVERALL_MEAN: 0.30},
        "fallback": {OVERALL_MEAN: 0.50, G_ENG_LIT: 0.30, BEST_HUMANITIES: 0.20},
    },
    "Computing": {
        "primary_gcse": G_COMPUTING,
        "primary": {G_COMPUTING: 0.70, G_MATHS: 0.30},
        "fallback": {G_MATHS: 0.60, OVERALL_MEAN: 0.40},
    },
    "Design Technology": {
        "primary_gcse": G_DT,
        "primary": {G_DT: 0.70, OVERALL_MEAN: 0.30},
        "fallback": {OVERALL_MEAN: 1.00},
    },
    "Drama": {
        "primary_gcse": G_DRAMA,
        "primary": {G_DRAMA: 0.60, G_ENG_LANG: 0.25, OVERALL_MEAN: 0.15},
        "fallback": {G_ENG_LANG: 0.60, OVERALL_MEAN: 0.40},
    },
    "Economics": {
        "primary_gcse": None,
        "primary": {G_MATHS: 0.50, G_ENG_LANG: 0.30, OVERALL_MEAN: 0.20},
        "fallback": {G_MATHS: 0.50, G_ENG_LANG: 0.30, OVERALL_MEAN: 0.20},
    },
    "English Literature": {
        "primary_gcse": G_ENG_LIT,
        "primary": {G_ENG_LIT: 0.70, G_ENG_LANG: 0.20, OVERALL_MEAN: 0.10},
        "fallback": {G_ENG_LANG: 0.60, OVERALL_MEAN: 0.40},
    },
    "Film Studies": {
        "primary_gcse": None,
        "primary": {G_ENG_LANG: 0.50, G_ENG_LIT: 0.30, OVERALL_MEAN: 0.20},
        "fallback": {G_ENG_LANG: 0.50, G_ENG_LIT: 0.30, OVERALL_MEAN: 0.20},
    },
    "French": {
        "primary_gcse": G_FRENCH,
        "primary": {G_FRENCH: 0.70, OVERALL_MEAN: 0.30},
        "fallback": {OVERALL_MEAN: 1.00},
    },
    "Geography": {
        "primary_gcse": G_GEOGRAPHY,
        "primary": {G_GEOGRAPHY: 0.70, OVERALL_MEAN: 0.30},
        "fallback": {BEST_HUMANITIES: 0.50, OVERALL_MEAN: 0.50},
    },
    "German": {
        "primary_gcse": G_GERMAN,
        "primary": {G_GERMAN: 0.70, OVERALL_MEAN: 0.30},
        "fallback": {OVERALL_MEAN: 1.00},
    },
    "History": {
        "primary_gcse": G_HISTORY,
        "primary": {G_HISTORY: 0.70, OVERALL_MEAN: 0.30},
        "fallback": {BEST_HUMANITIES: 0.50, OVERALL_MEAN: 0.50},
    },
    "Latin": {
        "primary_gcse": G_LATIN,
        "primary": {G_LATIN: 0.70, OVERALL_MEAN: 0.30},
        "fallback": {OVERALL_MEAN: 1.00},
    },
    "Mathematics": {
        "primary_gcse": G_MATHS,
        "primary": {G_MATHS: 0.70, OVERALL_MEAN: 0.30},
        "fallback": {OVERALL_MEAN: 1.00},
    },
    "Further Mathematics": {
        "primary_gcse": G_FURTHER_MATHS,
        "primary": {G_FURTHER_MATHS: 0.70, G_MATHS: 0.20, OVERALL_MEAN: 0.10},
        "fallback": {G_MATHS: 0.80, OVERALL_MEAN: 0.20},
    },
    "Music": {
        "primary_gcse": G_MUSIC,
        "primary": {G_MUSIC: 0.70, OVERALL_MEAN: 0.30},
        "fallback": {OVERALL_MEAN: 1.00},
    },
    "PE": {
        "primary_gcse": G_PE,
        "primary": {G_PE: 0.60, G_BIOLOGY: 0.25, OVERALL_MEAN: 0.15},
        "fallback": {OVERALL_MEAN: 0.50, G_BIOLOGY: 0.50},
    },
    "Physics": {
        "primary_gcse": G_PHYSICS,
        "primary": {G_PHYSICS: 0.60, G_MATHS: 0.25, OVERALL_MEAN: 0.15},
        "fallback": {OVERALL_MEAN: 0.60, G_MATHS: 0.40},
    },
    "Politics": {
        "primary_gcse": None,
        "primary": {OVERALL_MEAN: 0.50, BEST_HUMANITIES: 0.30, G_ENG_LANG: 0.20},
        "fallback": {OVERALL_MEAN: 0.50, BEST_HUMANITIES: 0.30, G_ENG_LANG: 0.20},
    },
    "Psychology": {
        "primary_gcse": G_BIOLOGY,
        "primary": {G_BIOLOGY: 0.40, G_MATHS: 0.30, G_ENG_LANG: 0.20, OVERALL_MEAN: 0.10},
        "fallback": {OVERALL_MEAN: 0.50, G_MATHS: 0.30, G_ENG_LANG: 0.20},
    },
    "RPE": {
        "primary_gcse": None,
        "primary": {OVERALL_MEAN: 0.50, BEST_HUMANITIES: 0.30, G_ENG_LIT: 0.20},
        "fallback": {OVERALL_MEAN: 0.50, BEST_HUMANITIES: 0.30, G_ENG_LIT: 0.20},
    },
    "Spanish": {
        "primary_gcse": G_SPANISH,
        "primary": {G_SPANISH: 0.70, OVERALL_MEAN: 0.30},
        "fallback": {OVERALL_MEAN: 1.00},
    },
}

ALL_A_LEVEL_SUBJECTS = sorted(DEFAULT_PROFILES.keys())

HUMANITIES_GCSE_COLS = [G_HISTORY, G_GEOGRAPHY, G_CLASSICS, G_RPE]
SCIENCE_GCSE_COLS = [G_BIOLOGY, G_CHEMISTRY, G_PHYSICS]


def get_profile(subject: str, user_overrides: dict | None = None) -> dict:
    """Return profile for subject, merging any user-edited weights."""
    base = DEFAULT_PROFILES.get(subject, {
        "primary_gcse": None,
        "primary": {OVERALL_MEAN: 1.00},
        "fallback": {OVERALL_MEAN: 1.00},
    })
    if user_overrides and subject in user_overrides:
        return {**base, **user_overrides[subject]}
    return base
