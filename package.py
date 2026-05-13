#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
package.py – Crea un archivio ZIP del plugin pronto per la distribuzione.

Output: kadas_sillages_<version>.zip nella root del repository.
Installabile via: KADAS/QGIS → Plugin → Gestisci plugin → Installa da ZIP

Uso:
    python package.py
    python package.py --output-dir dist/
    python package.py --version 1.2.3
"""
import argparse
import configparser
import os
import sys
import zipfile


# File/cartelle da escludere sempre dall'archivio
_EXCLUDE_NAMES = {"__pycache__", ".git", ".gitignore", ".DS_Store"}
_EXCLUDE_EXTS  = {".pyc", ".pyo", ".zip"}


def read_version(plugin_dir: str) -> str:
    meta = os.path.join(plugin_dir, "metadata.txt")
    cfg = configparser.ConfigParser()
    cfg.read(meta, encoding="utf-8")
    return cfg.get("general", "version", fallback="0.0.0")


def set_version(plugin_dir: str, version: str) -> None:
    """Aggiorna la versione in metadata.txt prima del packaging."""
    meta = os.path.join(plugin_dir, "metadata.txt")
    lines = []
    with open(meta, encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("version="):
                lines.append(f"version={version}\n")
            else:
                lines.append(line)
    with open(meta, "w", encoding="utf-8") as fh:
        fh.writelines(lines)


def should_include(path: str, name: str) -> bool:
    if name in _EXCLUDE_NAMES:
        return False
    _, ext = os.path.splitext(name)
    if ext in _EXCLUDE_EXTS:
        return False
    return True


def add_dir_to_zip(zf: zipfile.ZipFile, src_dir: str, zip_base: str) -> int:
    """
    Aggiunge ricorsivamente src_dir a zf sotto zip_base.
    Ritorna il numero di file aggiunti.
    """
    count = 0
    for root, dirs, files in os.walk(src_dir):
        # Filtra directory in-place
        dirs[:] = [d for d in dirs if should_include(root, d)]

        for filename in files:
            if not should_include(root, filename):
                continue
            full_path = os.path.join(root, filename)
            rel_path  = os.path.relpath(full_path, start=os.path.dirname(src_dir))
            arc_name  = os.path.join(zip_base, rel_path).replace("\\", "/")
            zf.write(full_path, arc_name)
            count += 1
    return count


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Crea il pacchetto ZIP di kadas_sillages per distribuzione."
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        dest="output_dir",
        help="Cartella di output (default: root del repository)",
    )
    parser.add_argument(
        "--version",
        default=None,
        help="Forza una versione specifica (aggiorna anche metadata.txt)",
    )
    args = parser.parse_args()

    repo_root  = os.path.dirname(os.path.abspath(__file__))
    plugin_dir = os.path.join(repo_root, "kadas_sillages")

    if not os.path.isdir(plugin_dir):
        print(f"[ERRORE] Cartella plugin non trovata: {plugin_dir}", file=sys.stderr)
        return 1

    # Aggiorna versione se richiesta
    if args.version:
        set_version(plugin_dir, args.version)
        print(f"metadata.txt aggiornato → version={args.version}")

    version    = read_version(plugin_dir)
    output_dir = args.output_dir or repo_root
    os.makedirs(output_dir, exist_ok=True)

    zip_name = f"kadas_sillages_{version}.zip"
    zip_path = os.path.join(output_dir, zip_name)

    print()
    print("=== KadasSillages – Package ===")
    print(f"  Versione : {version}")
    print(f"  Output   : {zip_path}")

    # Rimuovi zip precedente con stessa versione
    if os.path.isfile(zip_path):
        os.remove(zip_path)
        print("  (zip precedente rimosso)")

    # Crea archivio
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        n_files = add_dir_to_zip(zf, plugin_dir, zip_base="")

    size_kb = round(os.path.getsize(zip_path) / 1024, 1)
    print(f"\n✓ Archivio creato: {zip_name}  ({size_kb} KB, {n_files} file)")
    print(f"  Installabile via: KADAS → Plugin → Gestisci plugin → Installa da ZIP")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
