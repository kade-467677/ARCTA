"""ISO 16047 presentation only; persisted identifiers remain unchanged."""
import re

SYMBOLS = {"Xg": "T", "Xt": "T_th", "Xh": "T_b", "Y": "F", "A": "Θ",
           "A_eff": "Θ_recalé", "A0": "Θ₀", "µg": "µ_tot", "µt": "µ_th", "µh": "µ_b"}
LABELS = {
    "Xg": ("Couple de serrage T", "N·m"),
    "Xt": ("Couple transmis par le filetage T_th", "N·m"),
    "Xh": ("Couple de frottement à l’appui T_b", "N·m"),
    "Y": ("Force de serrage F", "N"), "A": ("Angle recalé Θ", "°"),
    "µg": ("Coefficient de frottement global µ_tot", "–"),
    "µt": ("Coefficient de frottement du filetage µ_th", "–"),
    "µh": ("Coefficient de frottement à l’appui µ_b", "–"),
}
_PATTERN = re.compile(r"(?<![\w])(" + "|".join(map(re.escape, sorted(SYMBOLS, key=len, reverse=True))) + r")(?![\w])")

def iso_text(value):
    """Convert a technical display label, never a filename or user free text."""
    text = str(value)
    # Human-readable rendering of technical curve identifiers.
    text = re.sub(r"(?<![\w])(TEST_COMPUTE_|TEST_)?(Xg|Xt|Xh|Y|µg|µt|µh)_?f(Xg|Xt|Xh|Y|A)(?![\w])",
                  lambda m: SYMBOLS[m[2]] + "=f(" + SYMBOLS[m[3]] + ")", text)
    text = re.sub(r"(µg|µt|µh)_COMPUTE_f(Xg|Y|A)",
                  lambda m: SYMBOLS[m[1]] + "=f(" + SYMBOLS[m[2]] + ")", text)
    return _PATTERN.sub(lambda m: SYMBOLS[m[0]], text)

def nomenclature_rows():
    return [{"Identifiant historique": key, "Symbole ISO 16047": SYMBOLS[key],
             "Grandeur": label, "Unité": unit} for key, (label, unit) in LABELS.items()]
