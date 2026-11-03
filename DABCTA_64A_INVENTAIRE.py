"""64A - Inventaire ARCTA en lecture seule ; aucune écriture SQL."""
import sys
from pathlib import Path

# 64J2 : auto-amorçage des imports paresseux arcta.* sans PYTHONPATH manuel.
_PROJECT_ROOT = Path(__file__).resolve().parent
for _candidate in (_PROJECT_ROOT / "src", _PROJECT_ROOT):
    _resolved = str(_candidate)
    if _resolved not in sys.path:
        sys.path.insert(0, _resolved)

import argparse
import hashlib
import json
import math
from collections import Counter
from datetime import date, datetime
from pathlib import Path

import openpyxl

TABLES = (
    "ARCTA_CONFIG_SYNTHESIS", "ARCTA_SETTINGS", "ARCTA_SOURCES",
    "POLY_FITS_STATS", "ARCTA_TOLERANCE_WARNINGS",
    "ARCTA_TOLERANCE_DETAILS", "ARCTA_SELF_LOCK_STATS", "ARCTA_SELFLOCK_CORRECTION",
    "ARCTA_MECHANICAL_MODES",
)
CURVES = set("MEAN MEDIAN MIN MAX STD Q1 Q3 IQR MAD MEAN_PLUS_2S "
             "MEAN_MINUS_2S MEAN_CI_LOW MEAN_CI_HIGH CI95_LOW CI95_HIGH MEDIAN_CI_LOW MEDIAN_CI_HIGH "
             "TOL_PARAM_LOW TOL_PARAM_HIGH TOL_NP_LOW TOL_NP_HIGH "
             "TOL_LOW TOL_HIGH".split())
TECHNICAL = set("N MEDIAN_CI_CONF_TARGET MEDIAN_CI_CONF_ACTUAL "
                "MEDIAN_CI_ORDER_LOW MEDIAN_CI_ORDER_HIGH SHAPIRO_P "
                "TOL_P TOL_CONF".split())
SETTINGS = set("THR_RATIO_DEFAULT ISO_TOL_P_CONTENT ISO_TOL_CONF_LEVEL "
               "ISO_MEDIAN_CONF_LEVEL NORMALITY_ALPHA NORMALITY_MIN_N".split())


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def table(book, name):
    if name not in book.sheetnames:
        return []
    rows = book[name].iter_rows(values_only=True)
    header = next(rows, ())
    if not header or any(not isinstance(k, str) or not k for k in header):
        raise ValueError(f"{name}: en-têtes absents ou invalides")
    if len(set(header)) != len(header):
        raise ValueError(f"{name}: en-têtes dupliqués")
    result = []
    for row in rows:
        if all(value is None for value in row):
            continue
        if any(isinstance(v, str) and v.startswith("=") for v in row):
            raise ValueError(f"{name}: formule inattendue dans un export")
        result.append(dict(zip(header, row)))
    return result


def finite(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def validate_polynomial(row):
    degree = row.get("Degree")
    if not finite(degree) or degree != int(degree) or not 0 <= degree <= 6:
        raise ValueError("Degré polynomial invalide")
    lo, hi = row.get("X_min"), row.get("X_max")
    if not finite(lo) or not finite(hi) or lo >= hi:
        raise ValueError("Domaine polynomial invalide")
    if not all(finite(row.get(f"coeff{i}")) for i in range(int(degree) + 1)):
        raise ValueError("Coefficient polynomial manquant ou non fini")
    if not all(row.get(k) for k in ("Compute_Sheet", "Type", "Stat")):
        raise ValueError("Identification polynomial incomplète")


def read_run(manifest_path):
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    run_id = manifest.get("run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("run_id absent")

    excel = manifest_path.parent / "result.xlsx"
    digest = sha256(excel)
    if digest != manifest.get("files_sha256", {}).get("result.xlsx"):
        raise ValueError("Empreinte de result.xlsx absente ou différente du manifeste")

    book = openpyxl.load_workbook(excel, read_only=True, data_only=False)
    try:
        tables = {name: table(book, name) for name in TABLES}
    finally:
        book.close()

    if sha256(excel) != digest:
        raise ValueError("Excel modifié pendant la lecture")
    for name in TABLES[:4]:
        if not tables[name]:
            raise ValueError(f"Feuille absente ou vide : {name}")

    config = tables["ARCTA_CONFIG_SYNTHESIS"]
    keys = [(r.get("Section"), r.get("Code")) for r in config]
    if any(not all(k) for k in keys) or len(keys) != len(set(keys)):
        raise ValueError("Codes de configuration absents ou dupliqués")
    fields = {
        r["Code"]: r.get("Valeur")
        for r in config if r["Section"] == "Configuration"
    }
    if not fields:
        raise ValueError("Configuration canonique absente")

    settings_rows = tables["ARCTA_SETTINGS"]
    settings = {r.get("Parameter"): r.get("Value") for r in settings_rows}
    if len(settings) != len(settings_rows) or not SETTINGS <= settings.keys():
        raise ValueError("Paramètres statistiques manquants ou dupliqués")
    settings.setdefault("MEAN_CI_CONF_LEVEL", .95)  # Niveau historique explicite
    for key in SETTINGS | {"MEAN_CI_CONF_LEVEL"}:
        value = settings[key]
        if not finite(value):
            raise ValueError(f"Paramètre non numérique : {key}")
        if key == "NORMALITY_MIN_N":
            valid = value == int(value) and 3 <= value <= 5000
        elif key == "THR_RATIO_DEFAULT":
            valid = 0 <= value < 1
        else:
            valid = 0 < value < 1
        if not valid:
            raise ValueError(f"Paramètre hors domaine : {key}")

    basis = settings.get("TORQUE_BASIS", "TOTAL")
    if basis not in {"TOTAL", "EFFECTIVE", "DUAL"}:
        raise ValueError("Référence de couple inconnue")
    if basis in {"EFFECTIVE", "DUAL"}:
        from arcta.run_mechanics import WINDOW
        if settings.get("SELFLOCK_METHOD") != WINDOW or not tables["ARCTA_SELFLOCK_CORRECTION"]:
            raise ValueError("Traçabilité de la correction autofrein absente")
        corrections = tables["ARCTA_SELFLOCK_CORRECTION"]
        retained = {str(r['Trial_ID']) for r in tables['ARCTA_SOURCES'] if r.get('Accepted_For_ARCTA') is True}
        if len({str(r.get('Trial_ID')) for r in corrections}) != len(corrections):
            raise ValueError("Correction autofrein dupliquée")
        if {str(r.get('Trial_ID')) for r in corrections} != retained:
            raise ValueError("Correction autofrein incomplète pour les essais retenus")
        if any(not finite(r.get('Autofrein_Nm')) or r['Autofrein_Nm'] < 0 or r.get('Method') != WINDOW or r.get('Torque_Basis') != 'EFFECTIVE' for r in corrections):
            raise ValueError("Correction autofrein invalide")
        from arcta.selflock_policy import validate_audit
        validate_audit(corrections, settings.get('SELFLOCK_POLICY'))
    if basis == "DUAL":
        from arcta.dual_campaign import validate_dual_export
        validate_dual_export(tables, manifest_path.parent, manifest)
    polynomials = tables["POLY_FITS_STATS"]
    identities = []
    for row in polynomials:
        validate_polynomial(row)
        if 'TORQUE_BASIS' in settings and (row.get('Torque_Basis') not in ({'TOTAL', 'EFFECTIVE', 'BOTH'} if basis == 'DUAL' else {basis}) or row.get('KK_Model') != settings.get('KK_MODEL')):
            raise ValueError("Convention mécanique des polynômes incohérente")
        modes = ("TOTAL", "EFFECTIVE") if row.get("Torque_Basis") == "BOTH" else (row.get("Torque_Basis", "TOTAL"),)
        # 64I1B : l'identité inclut le segment de validité S des tolérances.
        identities.extend((m, row["Compute_Sheet"], row["Type"], row["Stat"],
                           str(row.get("S", "") or "")) for m in modes)
        row["DABCTA_category"] = (
            "COURBE" if row["Stat"] in CURVES
            else "INDICATEUR" if row["Stat"] in TECHNICAL
            else "A_CLASSER"
        )
    if len(set(identities)) != len(identities):
        raise ValueError("Polynômes dupliqués dans le même run")

    sources = tables["ARCTA_SOURCES"]
    return {
        "run_id": run_id,
        "xlsx_sha256": digest,
        "copies": [str(manifest_path.parent.resolve())],
        "status": "LU",
        "manifest": manifest,
        "identity": {
            k: fields.get(k)
            for k in ("entity", "program_id", "configuration_id", "report_number")
        },
        "trial_count": len(sources),
        "accepted_count": sum(
            r.get("Accepted_For_ARCTA") is True for r in sources
        ),
        "config_fields": len(fields),
        "config_filled": sum(
            v is not None and v != "" for v in fields.values()
        ),
        "polynomial_categories": dict(
            Counter(r["DABCTA_category"] for r in polynomials)
        ),
        "families": dict(Counter(r["Type"] for r in polynomials)),
        "tables": tables,
    }

def inventory(root):
    root = Path(root).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"Dossier introuvable : {root}")

    runs, errors, seen = [], [], {}
    for path in sorted(root.rglob("ARCTA_RUN_MANIFEST.json")):
        try:
            run = read_run(path)
            key = (run["run_id"], run["xlsx_sha256"])
            if key in seen:
                seen[key]["copies"].extend(run["copies"])
            else:
                seen[key] = run
                runs.append(run)
        except Exception as exc:
            errors.append({"manifest": str(path), "error": str(exc)})

    counts = Counter(r["run_id"] for r in runs)
    for run in runs:
        if counts[run["run_id"]] > 1:
            run["status"] = "CONFLIT_RUN_ID"

    return {
        "schema": "DABCTA_INVENTORY_64A",
        "root": str(root),
        "runs": runs,
        "errors": errors,
        "note": (
            "Inventaire uniquement : LU ne constitue pas une validation "
            "scientifique ni un import SQL."
        ),
    }


def json_default(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"Valeur non sérialisable : {type(value).__name__}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "root", nargs="?", help="Dossier ARCTA_OUTPUTS à parcourir"
    )
    args = parser.parse_args()
    root = args.root or input("Dossier ARCTA_OUTPUTS : ").strip().strip('"')

    result = inventory(root)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    output = Path.cwd() / f"DABCTA_INVENTAIRE_{stamp}.json"
    content = json.dumps(
        result,
        ensure_ascii=False,
        indent=2,
        default=json_default,
        allow_nan=False,
    )
    with output.open("x", encoding="utf-8") as stream:
        stream.write(content)

    for run in result["runs"]:
        identity = " / ".join(
            str(v or "—") for v in run["identity"].values()
        )
        print(
            f"{run['status']} | {identity} | "
            f"{run['accepted_count']}/{run['trial_count']} essais | "
            f"{run['polynomial_categories']} | "
            f"{len(run['copies'])} copie(s)"
        )

    for error in result["errors"]:
        print(f"ERREUR : {error['manifest']} : {error['error']}")

    print(
        f"{len(result['runs'])} run(s) distinct(s), "
        f"{len(result['errors'])} erreur(s)."
    )
    print(f"Inventaire : {output}")
    if not result["runs"]:
        print("Aucun run lisible avec manifeste trouvé.")

    return 1 if (
        result["errors"]
        or any(r["status"] != "LU" for r in result["runs"])
    ) else 0


if __name__ == "__main__":
    raise SystemExit(main())
# 64G3A_MEAN_CI_NAMES
