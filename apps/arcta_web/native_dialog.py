"""Processus graphique séparé, utilisé uniquement sur le poste Windows local."""
import json
import sys


def main():
    import tkinter as tk
    from tkinter import filedialog
    mode, initial = sys.argv[1:3]
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        options = {"parent": root, "initialdir": initial or None}
        if mode == "directory":
            result = filedialog.askdirectory(title="Choisir le dossier des résultats", mustexist=True, **options)
            paths = [result] if result else []
        elif mode == "CONFIG":
            result = filedialog.askopenfilename(title="Choisir la CONFIG", filetypes=[("CONFIG Excel", "*.xlsx")], **options)
            paths = [result] if result else []
        else:
            paths = list(filedialog.askopenfilenames(title="Choisir les fichiers d'essai", filetypes=[("Essais", "*.xlsx *.csv *.txt")], **options))
        print(json.dumps(paths, ensure_ascii=True))
    finally:
        root.destroy()


if __name__ == "__main__":
    main()
