#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Convertidor universal con selección por elementos (Tkinter)
==========================================================
Mejoras clave respecto a tu script:
- Permite **elegir dentro de la carpeta** qué subcarpetas/archivos convertir con un
  **árbol con checkboxes** (selección múltiple, filtrado, expandir/colapsar).
- La conversión usa **solo** lo seleccionado (si no seleccionas nada, se toma TODO).
- Mantiene exportación a **PDF** (fpdf2), **TXT** y **CSV**.
- GUI no se bloquea durante la conversión (hilo en segundo plano).
- Lectura robusta de archivos de texto (UTF-8 con fallback).

Requisitos opcionales:
    python -m pip install fpdf2    # solo si deseas exportar PDF

Empaquetar a .EXE (Windows):
    python -m pip install pyinstaller
    pyinstaller --onefile --noconsole convertidor_gui_selectivo.py
"""
from __future__ import annotations

import csv
import os
import threading
from pathlib import Path
from tkinter import filedialog, messagebox, ttk, scrolledtext, IntVar, StringVar, Tk
import tkinter as tk

# ─────────────────────────────────────────────────────────────────────────────
#  Dependencia opcional para PDF
# ─────────────────────────────────────────────────────────────────────────────
try:
    from fpdf import FPDF  # type: ignore
except ImportError:  # pragma: no cover
    FPDF = None

# ─────────────────────────────────────────────────────────────────────────────
#  Utilidades de lectura
# ─────────────────────────────────────────────────────────────────────────────
TEXT_EXTS = {
    ".txt", ".md", ".csv", ".tsv",
    ".py", ".js", ".ts", ".json", ".yml", ".yaml", ".ini", ".cfg",
    ".log",
    ".html", ".css",
    ".xml",
    ".c", ".cpp", ".h", ".hpp", ".java", ".cs", ".go", ".rs", ".rb", ".php", ".swift",
    ".sh", ".bat", ".ps1", ".sql"
}

def is_text_file(path: Path) -> bool:
    if path.suffix.lower() in TEXT_EXTS:
        return True
    # Heurística: intentar decodificar un pequeño bloque como UTF-8
    try:
        with path.open("rb") as f:
            chunk = f.read(1024)
        chunk.decode("utf-8")
        return True
    except Exception:
        return False

def read_text_file(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="strict").splitlines(True)
    except Exception:
        try:
            return path.read_text(encoding="latin-1", errors="ignore").splitlines(True)
        except Exception:
            return []

# ─────────────────────────────────────────────────────────────────────────────
#  Escaneo + exportación respetando selección
# ─────────────────────────────────────────────────────────────────────────────
def file_is_allowed(file_path: Path, selected: set[Path] | None, base: Path) -> bool:
    """Devuelve True si el archivo debe incluirse según 'selected'.
    - selected=None o set()  → incluir todo
    - Si hay rutas en 'selected', incluir si:
        • El propio archivo está marcado, o
        • Su carpeta (o una ascendente) está marcada.
    """
    if not selected:
        return True
    # Normalizar a absolutos para comparación
    f_abs = file_path.resolve()
    for sel in selected:
        try:
            s_abs = sel.resolve()
        except Exception:
            continue
        if f_abs == s_abs:
            return True
        if s_abs.is_dir():
            try:
                f_abs.relative_to(s_abs)
                return True
            except ValueError:
                pass
    return False

def scan_project(base: Path, selected: set[Path] | None = None):
    """Devuelve (arbol, files) respetando la selección.
    - arbol: dict recursivo de carpetas→{...,'__files__':[nombres]}
    - files: lista [(ruta_relativa, [lineas]), ...]
    """
    arbol: dict[str, dict] = {}
    files: list[tuple[Path, list[str]]] = []

    for root, _, filenames in os.walk(base):
        root_path = Path(root)
        rel_root = root_path.relative_to(base)
        nodo = arbol
        if rel_root != Path("."):
            for parte in rel_root.parts:
                nodo = nodo.setdefault(parte, {})  # type: ignore[assignment]

        for name in filenames:
            ruta = root_path / name
            if not file_is_allowed(ruta, selected, base):
                continue
            nodo.setdefault("__files__", []).append(name)  # type: ignore[assignment]
            if is_text_file(ruta):
                lines = read_text_file(ruta)
            else:
                # Evitar volcar binarios al texto/CSV/PDF; pone marcador
                lines = [f"[BINARY FILE OMITTED: {ruta.name}]\n"]
            files.append((ruta.relative_to(base), lines))

    return arbol, files

def _tree_txt(nodo: dict, indent: int = 0):
    for k, v in sorted(nodo.items()):
        if k == "__files__":
            for f in sorted(v):
                yield " " * indent + f"- {f}"
        else:
            yield " " * indent + f"[{k}]/"
            yield from _tree_txt(v, indent + 4)

def export_txt(output: Path, arbol: dict, files: list[tuple[Path, list[str]]]):
    with output.open("w", encoding="utf-8") as fh:
        fh.write("# Árbol de archivos\n")
        fh.write("\n".join(_tree_txt(arbol)))
        fh.write("\n\n# Contenido de archivos\n\n")
        for rel_path, lines in files:
            fh.write(f"## {rel_path}\n")
            fh.writelines(lines)
            fh.write("\n")

def export_csv(output: Path, files: list[tuple[Path, list[str]]]):
    with output.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["path", "line_no", "content"])
        for rel_path, lines in files:
            for i, ln in enumerate(lines, 1):
                writer.writerow([str(rel_path), i, ln.rstrip("\n")])

def _draw_tree_pdf(pdf: "FPDF", nodo: dict, indent: int = 0):  # noqa: F722
    for k, v in sorted(nodo.items()):
        if k == "__files__":
            for f in sorted(v):
                pdf.multi_cell(0, 5, " " * indent + f"- {f}", new_x="LMARGIN", new_y="NEXT")
        else:
            pdf.multi_cell(0, 5, " " * indent + f"[{k}]/", new_x="LMARGIN", new_y="NEXT")
            _draw_tree_pdf(pdf, v, indent + 4)

def export_pdf(base: Path, output: Path, arbol: dict, files: list[tuple[Path, list[str]]]):
    if FPDF is None:
        raise RuntimeError("Instala primero fpdf2 →  python -m pip install fpdf2")

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_font("Courier", size=10)

    # Portada con árbol
    pdf.add_page()
    pdf.set_font("Courier", style="B", size=12)
    pdf.multi_cell(0, 8, f"Resumen de archivos en:\n{base}\n", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Courier", size=10)
    _draw_tree_pdf(pdf, arbol)

    # Contenido
    for rel_path, lines in files:
        pdf.add_page()
        pdf.set_font("Courier", style="B", size=11)
        pdf.multi_cell(0, 7, f"{rel_path}\n", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Courier", size=9)
        for ln in lines:
            pdf.multi_cell(0, 5, ln.encode("latin-1", "replace").decode("latin-1"), new_x="LMARGIN", new_y="NEXT")

    pdf.output(output)

# ─────────────────────────────────────────────────────────────────────────────
#  Diálogo de selección con árbol y checkboxes
# ─────────────────────────────────────────────────────────────────────────────
class CheckTreeDialog(tk.Toplevel):
    def __init__(self, master, root_path: Path, preselected: set[Path] | None = None):
        super().__init__(master)
        self.title("Seleccionar elementos dentro de la carpeta")
        self.geometry("720x520")
        self.minsize(640, 420)
        self.root_path = root_path
        self.preselected = set(preselected or [])
        self.result: set[Path] | None = None

        self._build_widgets()
        self._populate_tree()

        self.transient(master)
        self.grab_set()
        self.focus_set()

    def _build_widgets(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        # Barra superior
        bar = ttk.Frame(self)
        bar.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))
        for i in range(8):
            bar.columnconfigure(i, weight=0)
        bar.columnconfigure(8, weight=1)

        self.var_filter = tk.StringVar(value="")
        ttk.Label(bar, text="Filtro:").grid(row=0, column=0, padx=(0, 4))
        ent = ttk.Entry(bar, textvariable=self.var_filter, width=32)
        ent.grid(row=0, column=1, padx=(0, 8))
        ent.bind("<KeyRelease>", lambda e: self._filter_tree())

        ttk.Button(bar, text="Expandir todo", command=self._expand_all).grid(row=0, column=2, padx=4)
        ttk.Button(bar, text="Colapsar todo", command=self._collapse_all).grid(row=0, column=3, padx=4)
        ttk.Button(bar, text="Marcar visibles", command=self._check_visible).grid(row=0, column=4, padx=4)
        ttk.Button(bar, text="Desmarcar visibles", command=self._uncheck_visible).grid(row=0, column=5, padx=4)
        ttk.Button(bar, text="Marcar todo", command=self._check_all).grid(row=0, column=6, padx=4)
        ttk.Button(bar, text="Desmarcar todo", command=self._uncheck_all).grid(row=0, column=7, padx=4)

        # Árbol
        self.tree = ttk.Treeview(self, columns=("kind", "path"), show="tree")
        self.tree.grid(row=1, column=0, sticky="nsew", padx=(8,0), pady=(0,8))

        yscroll = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        yscroll.grid(row=1, column=1, sticky="ns", pady=(0,8))
        self.tree.configure(yscrollcommand=yscroll.set)

        # Click para alternar
        self.tree.bind("<Button-1>", self._on_click)

        # Botonera inferior
        btns = ttk.Frame(self)
        btns.grid(row=2, column=0, sticky="e", padx=8, pady=(0,8))
        ttk.Button(btns, text="Cancelar", command=self._cancel).grid(row=0, column=0, padx=6)
        ttk.Button(btns, text="Aceptar", command=self._accept).grid(row=0, column=1, padx=6)

        # Símbolos
        self.CHECKED = "☑"
        self.UNCHECKED = "☐"
        self.PARTIAL = "▣"
        self.checked: dict[str, str] = {}

    def _insert_item(self, parent_id: str, path: Path, is_dir: bool) -> str:
        pre = self.CHECKED if path in self.preselected else self.UNCHECKED
        text = f"{pre}  {path.name}{'/' if is_dir else ''}"
        iid = self.tree.insert(parent_id, "end", text=text, values=("dir" if is_dir else "file", str(path)))
        self.checked[iid] = "checked" if pre == self.CHECKED else "unchecked"
        return iid

    def _populate_tree(self):
        root_id = self._insert_item("", self.root_path, True)
        self.tree.item(root_id, open=True)

        def add_children(parent_id: str, parent_path: Path):
            try:
                entries = sorted(parent_path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
            except PermissionError:
                entries = []
            for p in entries:
                is_dir = p.is_dir()
                iid = self._insert_item(parent_id, p, is_dir)
                if is_dir:
                    add_children(iid, p)
        add_children(root_id, self.root_path)

    def _toggle_item(self, iid: str, target_state: str | None = None):
        current = self.checked.get(iid, "unchecked")
        new_state = target_state or ("unchecked" if current == "checked" else "checked")
        self.checked[iid] = new_state
        text = self.tree.item(iid, "text")
        mark = self.CHECKED if new_state == "checked" else self.UNCHECKED
        self.tree.item(iid, text=mark + text[1:])

        # Hijos
        for child in self.tree.get_children(iid):
            self._toggle_item(child, new_state)

        # Padres (estado parcial)
        self._update_parents(iid)

    def _update_parents(self, iid: str):
        parent = self.tree.parent(iid)
        if not parent:
            return
        states = [self.checked.get(c, "unchecked") for c in self.tree.get_children(parent)]
        if all(s == "checked" for s in states):
            self.checked[parent] = "checked"
            mark = self.CHECKED
        elif all(s == "unchecked" for s in states):
            self.checked[parent] = "unchecked"
            mark = self.UNCHECKED
        else:
            self.checked[parent] = "partial"
            mark = self.PARTIAL

        text = self.tree.item(parent, "text")
        self.tree.item(parent, text=mark + text[1:])
        self._update_parents(parent)

    def _on_click(self, event):
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        self._toggle_item(iid)

    def _expand_all(self):
        def rec(iid):
            self.tree.item(iid, open=True)
            for c in self.tree.get_children(iid):
                rec(c)
        for iid in self.tree.get_children(""):
            rec(iid)

    def _collapse_all(self):
        def rec(iid):
            self.tree.item(iid, open=False)
            for c in self.tree.get_children(iid):
                rec(c)
        for iid in self.tree.get_children(""):
            rec(iid)

    def _filter_tree(self):
        pattern = self.var_filter.get().lower().strip()

        def matches(name: str) -> bool:
            return pattern in name.lower()

        # Aplicar/rehabilitar usando detach/reattach
        def rec(iid: str) -> bool:
            name = self.tree.item(iid, "text")[2:]  # quitar símbolo + espacio
            path_str = self.tree.set(iid, "path")
            visible_self = (not pattern) or matches(name) or (path_str and matches(path_str))
            child_visible = False
            for c in self.tree.get_children(iid):
                if rec(c):
                    child_visible = True
            visible = visible_self or child_visible
            if visible:
                try:
                    self.tree.reattach(iid, self.tree.parent(iid), "end")
                except tk.TclError:
                    pass
            else:
                try:
                    self.tree.detach(iid)
                except tk.TclError:
                    pass
            return visible

        for iid in self.tree.get_children(""):
            rec(iid)

    def _iter_all_items(self):
        stack = list(self.tree.get_children(""))
        while stack:
            iid = stack.pop()
            yield iid
            stack.extend(self.tree.get_children(iid))

    def _check_visible(self):
        # Elementos "adjuntos" están visibles
        for iid in list(self._iter_all_items()):
            try:
                self.tree.index(iid)  # lanza si está detached
                self._toggle_item(iid, "checked")
            except tk.TclError:
                pass

    def _uncheck_visible(self):
        for iid in list(self._iter_all_items()):
            try:
                self.tree.index(iid)
                self._toggle_item(iid, "unchecked")
            except tk.TclError:
                pass

    def _check_all(self):
        for iid in self._iter_all_items():
            self._toggle_item(iid, "checked")

    def _uncheck_all(self):
        for iid in self._iter_all_items():
            self._toggle_item(iid, "unchecked")

    def _gather_checked_paths(self) -> set[Path]:
        selected: set[Path] = set()
        for iid, state in self.checked.items():
            if state == "checked":
                path_str = self.tree.set(iid, "path")
                if path_str:
                    selected.add(Path(path_str))
        return selected

    def _accept(self):
        sel = self._gather_checked_paths()
        if not sel:
            if not messagebox.askyesno(
                "Sin selección",
                "No has marcado nada. ¿Deseas convertir TODOS los elementos?"
            ):
                return  # Seguir en el diálogo
        self.result = sel
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()

# ─────────────────────────────────────────────────────────────────────────────
#  GUI principal
# ─────────────────────────────────────────────────────────────────────────────
class ConvertidorGUI:
    def __init__(self) -> None:
        self.root = Tk()
        self.root.title("Convertidor universal (PDF / TXT / CSV)")
        self.root.geometry("720x520")

        self.project_path = StringVar()
        self.output_name = StringVar(value="listado")
        self.format_var = IntVar(value=0)  # 0 = PDF, 1 = TXT, 2 = CSV
        self.selected_paths: set[Path] | None = set()  # None o set() → todo

        self._build_layout()

    def _build_layout(self):
        padding = {"padx": 8, "pady": 4}

        # Selección de carpeta
        frm_top = ttk.Frame(self.root)
        frm_top.pack(fill="x", **padding)

        ttk.Label(frm_top, text="Carpeta del proyecto:").pack(side="left")
        ttk.Entry(frm_top, textvariable=self.project_path, width=54).pack(side="left", padx=(4, 0))
        ttk.Button(frm_top, text="Examinar…", command=self._select_folder).pack(side="left", padx=4)

        # Nombre de salida
        frm_out = ttk.Frame(self.root)
        frm_out.pack(fill="x", **padding)
        ttk.Label(frm_out, text="Nombre de salida (sin extensión):").pack(side="left")
        ttk.Entry(frm_out, textvariable=self.output_name, width=32).pack(side="left", padx=(4, 0))

        # Formato
        frm_fmt = ttk.LabelFrame(self.root, text="Formato")
        frm_fmt.pack(fill="x", **padding)
        ttk.Radiobutton(frm_fmt, text="PDF", variable=self.format_var, value=0).pack(side="left", padx=10)
        ttk.Radiobutton(frm_fmt, text="TXT", variable=self.format_var, value=1).pack(side="left", padx=10)
        ttk.Radiobutton(frm_fmt, text="CSV", variable=self.format_var, value=2).pack(side="left", padx=10)

        # Selección interna
        frm_sel = ttk.Frame(self.root)
        frm_sel.pack(fill="x", **padding)
        ttk.Button(frm_sel, text="Seleccionar elementos dentro…", command=self._open_selector).pack(side="left")
        self.lbl_sel = ttk.Label(frm_sel, text="(Actualmente: todo)")
        self.lbl_sel.pack(side="left", padx=8)

        # Ejecutar
        ttk.Button(self.root, text="Convertir", command=self._run_conversion).pack(**padding)

        # Log
        self.log = scrolledtext.ScrolledText(self.root, height=12, state="disabled", font=("Consolas", 10))
        self.log.pack(fill="both", expand=True, **padding)

    # Callbacks
    def _select_folder(self):
        path = filedialog.askdirectory(title="Selecciona la carpeta del proyecto")
        if path:
            self.project_path.set(path)
            # al cambiar carpeta, vaciar selección previa
            self.selected_paths = set()
            self._update_sel_label()

    def _open_selector(self):
        base = Path(self.project_path.get()).expanduser()
        if not base.is_dir():
            messagebox.showerror("Error", "Debes seleccionar una carpeta válida primero.")
            return
        dlg = CheckTreeDialog(self.root, base, self.selected_paths or set())
        # Esperar a que se cierre
        self.root.wait_window(dlg)
        if dlg.result is not None:
            # Si devuelve set vacío → significa "todo"
            self.selected_paths = set(dlg.result)
            self._update_sel_label()

    def _update_sel_label(self):
        if not self.selected_paths:
            self.lbl_sel.configure(text="(Actualmente: todo)")
        else:
            n_dirs = sum(1 for p in self.selected_paths if Path(p).is_dir())
            n_files = sum(1 for p in self.selected_paths if Path(p).is_file())
            self.lbl_sel.configure(text=f"Seleccionados: {n_dirs} carpetas, {n_files} archivos")

    def _run_conversion(self):
        threading.Thread(target=self._convert, daemon=True).start()

    def _convert(self):
        base = Path(self.project_path.get()).expanduser().resolve()
        name = self.output_name.get().strip() or "listado"
        fmt = ("pdf", "txt", "csv")[self.format_var.get()]

        if not base.is_dir():
            messagebox.showerror("Error", "Debes seleccionar una carpeta válida")
            return

        output = Path.cwd() / f"{name}.{fmt}"

        self._log(f"📂 Carpeta: {base}")
        self._log(f"🧩 Selección: {'todo' if not self.selected_paths else f'{len(self.selected_paths)} elementos'}")
        self._log(f"💾 Salida : {output}")
        self._log(f"📄 Formato: {fmt.upper()}")
        self._log("──────────────────────────────────────────────────────")

        try:
            arbol, files = scan_project(base, self.selected_paths if self.selected_paths else None)
            if fmt == "pdf":
                export_pdf(base, output, arbol, files)
            elif fmt == "txt":
                export_txt(output, arbol, files)
            else:
                export_csv(output, files)
            self._log(f"✅ Conversión completada → {output}\n")
            messagebox.showinfo("Éxito", f"Archivo generado:\n{output}")
        except Exception as exc:
            self._log(f"❌ Error: {exc}\n")
            messagebox.showerror("Error", str(exc))

    def _log(self, text: str):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.configure(state="disabled")
        self.log.see("end")

    def run(self):
        self.root.mainloop()

# ─────────────────────────────────────────────────────────────────────────────
#  Arranque
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    ConvertidorGUI().run()
