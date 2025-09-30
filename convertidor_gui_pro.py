# -*- coding: utf-8 -*-
"""
Convertidor Universal Pro - VERSIÓN FINAL CORREGIDA
===================================================
Versión definitiva que corrige el AttributeError final relacionado con el orden
de inicialización de la UI y la carga de la configuración.
"""
from __future__ import annotations

import csv
import os
import json
import queue
import threading
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk, scrolledtext, IntVar, StringVar, Tk
import tkinter as tk

# Dependencias externas (requieren 'pip install sv-ttk tkinterdnd2 fpdf2')
import sv_ttk
from tkinterdnd2 import DND_FILES, TkinterDnD

try:
    from fpdf import FPDF
except ImportError:
    FPDF = None

# ─────────────────────────────────────────────────────────────────────────────
#  LÓGICA DE PROCESAMIENTO DE ARCHIVOS
# ─────────────────────────────────────────────────────────────────────────────

def read_text_file(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="strict").splitlines(True)
    except Exception:
        try:
            return path.read_text(encoding="latin-1", errors="ignore").splitlines(True)
        except Exception:
            return ["[ERROR: No se pudo leer el archivo]\n"]

def file_is_allowed(file_path: Path, selected_resolved: set[Path] | None) -> bool:
    if not selected_resolved:
        return True
    f_abs = file_path.resolve()
    for sel in selected_resolved:
        if f_abs == sel or (sel.is_dir() and sel in f_abs.parents):
            return True
    return False

def scan_project(base: Path, selected: set[Path] | None, log_queue: queue.Queue):
    arbol, files = {}, []
    selected_resolved = {p.resolve() for p in selected} if selected else None
    log_queue.put("-> Iniciando escaneo de directorios...")
    
    all_paths = [p for p in base.rglob('*') if p.is_file()]
    total_files_scan = len(all_paths)
    
    for i, ruta_completa in enumerate(all_paths):
        if i % 100 == 0:
            log_queue.put(('progress', (i / max(1, total_files_scan)) * 20))
        
        if not file_is_allowed(ruta_completa, selected_resolved):
            continue
        
        rel_path = ruta_completa.relative_to(base)
        nodo = arbol
        for parte in rel_path.parent.parts:
            nodo = nodo.setdefault(parte, {})
        nodo.setdefault("__files__", []).append(rel_path.name)
        
        lines = read_text_file(ruta_completa)
        files.append((rel_path, lines))
        
    log_queue.put(f"-> Escaneo finalizado. Se procesarán {len(files)} archivos.")
    return arbol, files

def _tree_txt(nodo: dict, indent: int = 0):
    for k, v in sorted(nodo.items()):
        if k == "__files__":
            for f in sorted(v):
                yield " " * indent + f"- {f}"
        else:
            yield " " * indent + f"[{k}]/"
            yield from _tree_txt(v, indent + 4)

def export_txt(
    output: Path,
    arbol: dict,
    files: list[tuple[Path, list[str]]],
    ext_filter: tuple[set[str], set[str]] | None,
    log_queue: queue.Queue
):
    log_queue.put("-> Generando archivo TXT...")
    total = len(files)

    def should_convert(rel_path: Path) -> bool:
        if ext_filter is None:
            return True
        includes, excludes = ext_filter
        ext = rel_path.suffix.lower()
        # Si hay inclusiones, solo pasan las incluidas
        if includes and ext not in includes:
            return False
        # En cualquier caso, excluidas nunca pasan
        if ext in excludes:
            return False
        return True

    with output.open("w", encoding="utf-8") as fh:
        fh.write("# Árbol de archivos\n" + "\n".join(_tree_txt(arbol)) + "\n\n# Contenido de archivos\n\n")
        for i, (rel_path, lines) in enumerate(files):
            if i % 50 == 0:
                log_queue.put(('progress', 20 + (i / max(1, total)) * 80))
            if should_convert(rel_path):
                fh.write(f"## {rel_path}\n{''.join(lines)}\n")
            else:
                fh.write(f"## {rel_path} [no convertido]\n")
    log_queue.put("-> Archivo TXT generado.")


def parse_exts(spec: str) -> tuple[set[str], set[str]] | None:
    """
    Devuelve:
      None                  -> convertir todo
      (includes, excludes)  -> conjuntos normalizados de extensiones
    Reglas:
      - Inclusión:   .py,.md           (sin '!')
      - Exclusión:   !pdf,!jpg         (con '!')
      - Mixto:       .py,.md,!pdf      (incluye solo .py/.md y además excluye .pdf)
      - Todo:        *                 (o vacío)
    """
    if not spec or spec.strip() in {"*", "todos", "TODOS"}:
        return None

    inc: set[str] = set()
    exc: set[str] = set()
    parts = [p.strip() for p in spec.split(",") if p.strip()]
    for p in parts:
        if p.startswith("!"):
            ext = "." + p[1:].lstrip(".").lower()
            exc.add(ext)
        else:
            ext = "." + p.lstrip(".").lower()
            inc.add(ext)

    if not inc and not exc:
        return None
    return (inc, exc)




# ─────────────────────────────────────────────────────────────────────────────
#  CLASE CheckTreeDialog (VERSIÓN FINAL)
# ─────────────────────────────────────────────────────────────────────────────

class CheckTreeDialog(tk.Toplevel):
    def __init__(self, master, root_path: Path, preselected: set[Path] | None = None):
        super().__init__(master)
        self.title("Selección Avanzada de Elementos")
        self.geometry("800x600")
        self.minsize(700, 500)

        self.root_path = root_path
        self.preselected = set(preselected or [])
        self.result: set[Path] | None = None

        self.checked: dict[str, str] = {}
        self.item_paths: dict[str, Path] = {}
        self.filter_name_var = tk.StringVar()
        self.filter_ext_var = tk.StringVar()
        self._filter_job = None

        self._build_widgets()
        self._populate_tree()

        self.transient(master)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.focus_set()
        self.filter_name_var.trace_add("write", self._schedule_filter)
        self.filter_ext_var.trace_add("write", self._schedule_filter)

    def _build_widgets(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        main_frame = ttk.Frame(self, padding=10)
        main_frame.grid(row=0, column=0, sticky="nsew")
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(1, weight=1)

        filter_frame = ttk.LabelFrame(main_frame, text="Filtros", padding=10)
        filter_frame.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        filter_frame.columnconfigure(1, weight=1)
        filter_frame.columnconfigure(3, weight=1)
        
        ttk.Label(filter_frame, text="Nombre:").grid(row=0, column=0, padx=(0, 5))
        ttk.Entry(filter_frame, textvariable=self.filter_name_var).grid(row=0, column=1, sticky="ew")
        ttk.Label(filter_frame, text="Extensión (ej: .txt):").grid(row=0, column=2, padx=(10, 5))
        ttk.Entry(filter_frame, textvariable=self.filter_ext_var, width=15).grid(row=0, column=3, sticky="ew")

        tree_frame = ttk.Frame(main_frame)
        tree_frame.grid(row=1, column=0, sticky="nsew")
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)
        
        actions_frame = ttk.LabelFrame(main_frame, text="Acciones", padding=10)
        actions_frame.grid(row=1, column=1, sticky="ns", padx=(10, 0))
        
        ttk.Button(actions_frame, text="Marcar Todos", command=self._select_all).pack(fill="x", pady=2)
        ttk.Button(actions_frame, text="Desmarcar Todos", command=self._deselect_all).pack(fill="x", pady=2)
        ttk.Button(actions_frame, text="Invertir Selección", command=self._invert_selection).pack(fill="x", pady=2)
        
        self.tree = ttk.Treeview(tree_frame, show="tree")
        self.tree.grid(row=0, column=0, sticky="nsew")
        
        yscroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        yscroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=yscroll.set)

        self.tree.bind("<<TreeviewOpen>>", self._on_tree_open)
        self.tree.bind("<Button-1>", self._on_click)

        bottom_frame = ttk.Frame(main_frame)
        bottom_frame.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        bottom_frame.columnconfigure(0, weight=1)
        
        self.status_label = ttk.Label(bottom_frame, text="0 elementos seleccionados")
        self.status_label.grid(row=0, column=0, sticky="w")
        
        btn_container = ttk.Frame(bottom_frame)
        btn_container.grid(row=0, column=1, sticky="e")
        ttk.Button(btn_container, text="Cancelar", command=self._cancel).pack(side="left", padx=5)
        ttk.Button(btn_container, text="Aceptar", style="Accent.TButton", command=self._accept).pack(side="left")

        self.CHECKED, self.UNCHECKED = "☑", "☐"

    def _populate_tree(self):
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        
        self.checked.clear()
        self.item_paths.clear()

        root_iid = self._insert_item("", self.root_path, True, open_node=True)
        self._load_children(root_iid)
        self._update_selection_count()

    def _load_children(self, parent_iid):
        parent_path = self.item_paths[parent_iid]
        
        children = self.tree.get_children(parent_iid)
        if children:
            self.tree.delete(*children)
        
        try:
            filter_name = self.filter_name_var.get().lower()
            filter_ext = self.filter_ext_var.get().lower()

            entries = sorted(parent_path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
            for path in entries:
                is_dir = path.is_dir()
                name_lower = path.name.lower()

                if filter_name and filter_name not in name_lower:
                    continue
                if not is_dir and filter_ext and not name_lower.endswith(filter_ext):
                    continue

                self._insert_item(parent_iid, path, is_dir)
            
            self._toggle_item(parent_iid, self.checked.get(parent_iid), update_logic=True)
        except (PermissionError, FileNotFoundError):
            pass

    def _on_tree_open(self, event):
        if not self.tree.selection(): return
        iid = self.tree.selection()[0]
        children = self.tree.get_children(iid)
        if children and self.tree.item(children[0], "text") == "":
            self._load_children(iid)

    def _insert_item(self, parent_id: str, path: Path, is_dir: bool, open_node: bool = False):
        display_name = f" {path.name}{'/' if is_dir else ''}"
        iid = self.tree.insert(parent_id, "end", text=display_name, open=open_node)
        
        self.item_paths[iid] = path
        initial_state = "checked" if path in self.preselected else "unchecked"
        self._update_item_visuals(iid, initial_state)

        if is_dir:
            try:
                if any(path.iterdir()):
                    self.tree.insert(iid, "end", text="")
            except (PermissionError, FileNotFoundError):
                pass
        return iid

    def _schedule_filter(self, *args):
        if self._filter_job:
            self.after_cancel(self._filter_job)
        self._filter_job = self.after(250, self._populate_tree)

    def _update_item_visuals(self, iid, state):
        self.checked[iid] = state
        mark = self.CHECKED if state == "checked" else self.UNCHECKED
        current_text = self.tree.item(iid, "text").lstrip(f"{self.CHECKED}{self.UNCHECKED}▣ ").lstrip()
        self.tree.item(iid, text=f"{mark} {current_text}")

    def _on_click(self, event):
        iid = self.tree.identify_row(event.y)
        if not iid or self.tree.identify_region(event.x, event.y) != "tree":
            return
        self._toggle_item(iid)

    def _toggle_item(self, iid: str, target_state: str | None = None, update_logic: bool = True):
        current = self.checked.get(iid, "unchecked")
        new_state = target_state if target_state is not None else ("unchecked" if current == "checked" else "checked")
        
        self._update_item_visuals(iid, new_state)

        if update_logic:
            for child in self.tree.get_children(iid):
                if child in self.checked:
                    self._toggle_item(child, new_state, update_logic=True)
            self._update_parents_visuals(iid)
        
        self._update_selection_count()

    def _update_parents_visuals(self, iid: str):
        parent_iid = self.tree.parent(iid)
        if not parent_iid: return

        child_iids = self.tree.get_children(parent_iid)
        if not child_iids or all(c not in self.checked for c in child_iids): return

        states = [self.checked.get(c, "unchecked") for c in child_iids if c in self.checked]
        
        if all(s == "checked" for s in states):
            new_parent_state = "checked"
        else:
            new_parent_state = "unchecked"
        
        self._update_item_visuals(parent_iid, new_parent_state)
        self._update_parents_visuals(parent_iid)

    def _update_selection_count(self):
        count = sum(1 for state in self.checked.values() if state == "checked")
        self.status_label.config(text=f"{count} elemento{'s' if count != 1 else ''} seleccionado{'s' if count != 1 else ''}")

    def _select_all(self):
        for iid in self.item_paths: self._toggle_item(iid, "checked", update_logic=False)
        for iid in self.item_paths: self._update_parents_visuals(iid)
        self._update_selection_count()

    def _deselect_all(self):
        for iid in self.item_paths: self._toggle_item(iid, "unchecked", update_logic=False)
        for iid in self.item_paths: self._update_parents_visuals(iid)
        self._update_selection_count()
        
    def _invert_selection(self):
        for iid in list(self.item_paths.keys()):
            current_state = self.checked.get(iid, "unchecked")
            self._toggle_item(iid, "unchecked" if current_state == "checked" else "checked", update_logic=False)
        for iid in self.item_paths: self._update_parents_visuals(iid)
        self._update_selection_count()

    def _accept(self):
        self.result = {path for iid, path in self.item_paths.items() if self.checked.get(iid) == "checked"}
        if not self.result:
            if not messagebox.askyesno("Sin Selección", "No has marcado nada. ¿Deseas procesar TODOS los elementos de la carpeta?"):
                return
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()

# ─────────────────────────────────────────────────────────────────────────────
#  GUI PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────

class ConvertidorGUI:
    CONFIG_FILE = Path.home() / ".convertidor_universal_config.json"

    def __init__(self) -> None:
        self.root = TkinterDnD.Tk()
        self.root.title("Convertidor Universal Pro")
        self.root.geometry("850x650")
        self.root.minsize(700, 500)

        # Crear todas las variables de estado ANTES de cualquier otra cosa.
        self.project_path = StringVar()
        self.output_name = StringVar(value="listado")
        self.format_var = IntVar(value=1)
        self.theme_var = tk.StringVar(value="dark")
        self.preset_var = StringVar(value="* (Todo)")
        self.exts_var = StringVar(value="*")  # editable por el usuario
        self.selected_paths: set[Path] = set()
        self.last_output_path: Path | None = None
        self.log_queue = queue.Queue()
        
        # CORRECCIÓN DEL ORDEN DE INICIALIZACIÓN:
        # 1. Construir la UI (para que el widget 'self.log' exista).
        self._build_layout()
        # 2. Cargar la configuración (que puede escribir en 'self.log').
        self._load_config()
        # 3. Iniciar los listeners.
        self._process_log_queue()
        self.entry_path.drop_target_register(DND_FILES)
        self.entry_path.dnd_bind('<<Drop>>', self._handle_drop)
    
    def _on_theme_change(self):
        """
        Se ejecuta DESPUÉS de que el switch cambia la variable.
        Aplica el nuevo tema y guarda la configuración.
        """
        # 1. Leer el NUEVO estado de la variable (que el switch ya cambió)
        new_theme = self.theme_var.get()
        
        # 2. Aplicar el tema visualmente
        sv_ttk.set_theme(new_theme)
        
        # 3. Guardar la nueva configuración
        self._save_config()
        self._log(f"Tema cambiado a '{new_theme}'.")

    def _build_layout(self):
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(3, weight=1)
        
        main_controls = ttk.Frame(self.root, padding=10)
        main_controls.grid(row=0, column=0, sticky="ew")
        main_controls.columnconfigure(1, weight=1)

        ttk.Label(main_controls, text="Carpeta de Proyecto:").grid(row=0, column=0, padx=(0, 5), sticky="w")
        self.entry_path = ttk.Entry(main_controls, textvariable=self.project_path)
        self.entry_path.grid(row=0, column=1, sticky="ew")
        
        self.btn_browse = ttk.Button(main_controls, text="Examinar...", command=self._select_folder)
        self.btn_browse.grid(row=0, column=2, padx=(5, 0))

        self.theme_switch = ttk.Checkbutton(
            main_controls, text="Modo Oscuro", style="Switch.TCheckbutton",
            variable=self.theme_var, onvalue="dark", offvalue="light",
            command=self._on_theme_change)
        self.theme_switch.grid(row=0, column=3, padx=(15, 0))

        settings_frame = ttk.Frame(self.root, padding=(10, 5))
        settings_frame.grid(row=1, column=0, sticky="ew")
        settings_frame.columnconfigure(0, weight=1)

        out_group = ttk.LabelFrame(settings_frame, text="Configuración de Salida", padding=10)
        out_group.grid(row=0, column=0, sticky="ew")
        out_group.columnconfigure(1, weight=1)

        ttk.Label(out_group, text="Nombre de salida:").grid(row=0, column=0, sticky="w")
        self.entry_output = ttk.Entry(out_group, textvariable=self.output_name)
        self.entry_output.grid(row=0, column=1, padx=(5, 10), sticky="ew")
        
        self.frm_fmt = ttk.Frame(out_group)
        self.frm_fmt.grid(row=0, column=2)
        ttk.Radiobutton(self.frm_fmt, text="PDF", variable=self.format_var, value=0).pack(side="left", padx=5)
        ttk.Radiobutton(self.frm_fmt, text="TXT", variable=self.format_var, value=1).pack(side="left", padx=5)
        ttk.Radiobutton(self.frm_fmt, text="CSV", variable=self.format_var, value=2).pack(side="left", padx=5)
        
        sel_group = ttk.LabelFrame(settings_frame, text="Selección de Contenido", padding=10)
        sel_group.grid(row=1, column=0, sticky="ew", pady=5)

        self.btn_selector = ttk.Button(sel_group, text="Seleccionar archivos/carpetas...", command=self._open_selector)
        self.btn_selector.pack(side="left")
        self.lbl_sel = ttk.Label(sel_group, text="(Actualmente: todo)")
        self.lbl_sel.pack(side="left", padx=8)

        exts_group = ttk.LabelFrame(settings_frame, text="Filtros de conversión", padding=10)
        exts_group.grid(row=2, column=0, sticky="ew", pady=(5, 0))
        exts_group.columnconfigure(1, weight=1)

        # Presets
        ttk.Label(exts_group, text="Preset:").grid(row=0, column=0, sticky="w")
        self.cmb_presets = ttk.Combobox(
            exts_group,
            textvariable=self.preset_var,
            values=[
                "* (Todo)",
                ".md,.txt (Markdown/Texto)",
                ".py,.ts,.js (Código típico)",
                ".c,.cpp,.h (C/C++)",
                ".java,.kt (JVM)",
                ".json,.yml,.yaml,.toml (Config)",
                ".sh,.ps1,.bat (Scripts)",
                ".tex,.bib (LaTeX)",

                # EXCLUSIONES (todo excepto…)
                "!pdf (Todo excepto PDF)",
                "!pdf,!jpg,!jpeg,!png,!gif (Todo excepto imágenes y PDF)",
                "!mp3,!wav,!flac (Todo excepto audio)",
                "!mp4,!mkv,!avi (Todo excepto vídeo)",
                "!zip,!rar,!7z,!tar,!gz (Todo excepto comprimidos)",

                # MIXTOS (incluye solo X e, además, excluye Y)
                ".py,.md,!pdf (Código/MD sin PDF)",
                ".ipynb,.py,!png,!jpg (Notebooks + Py, sin imágenes)",
                ".json,.yml,.yaml,!lock (Configs, excluye *lock)",
            ],
            state="readonly",
        )
        self.cmb_presets.grid(row=0, column=1, sticky="ew", padx=(5, 10))

        # Campo editable (si no está en la lista, el usuario lo escribe)
        ttk.Label(exts_group, text="Extensiones a convertir:").grid(row=1, column=0, sticky="w", pady=(6,0))
        entry_frame = ttk.Frame(exts_group)
        entry_frame.grid(row=1, column=1, sticky="ew", padx=(5, 10), pady=(6,0))
        entry_frame.columnconfigure(0, weight=1)

        self.entry_exts = ttk.Entry(entry_frame, textvariable=self.exts_var)
        self.entry_exts.grid(row=0, column=0, sticky="ew")

        # Botón de ayuda que abre modal
        self.btn_exts_help = ttk.Button(entry_frame, text="ℹ️", width=3, command=self._show_exts_help)
        self.btn_exts_help.grid(row=0, column=1, padx=(6,0))

        # Pista corta (opcional) a la derecha
        ttk.Label(exts_group, text="Ej.: *, .py,.md  |  !pdf  |  .py,.md,!pdf").grid(
            row=1, column=2, sticky="w", pady=(6,0)
        )



        # Vincular cambio de preset
        self.cmb_presets.bind("<<ComboboxSelected>>", lambda e: self._on_preset_change())


        action_frame = ttk.Frame(self.root, padding=(10, 5))
        action_frame.grid(row=2, column=0, sticky="ew")
        action_frame.columnconfigure(0, weight=1)

        self.btn_convert = ttk.Button(action_frame, text="Convertir", style="Accent.TButton", command=self._run_conversion)
        self.btn_convert.grid(row=0, column=0, sticky="ew")
        
        self.progress_bar = ttk.Progressbar(action_frame, orient="horizontal", mode="determinate")
        self.progress_bar.grid(row=1, column=0, sticky="ew", pady=5)

        log_frame = ttk.LabelFrame(self.root, text="Registro de Actividad", padding=10)
        log_frame.grid(row=3, column=0, sticky="nsew", padx=10, pady=5)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.log = scrolledtext.ScrolledText(log_frame, state="disabled", font=("Consolas", 10), wrap="word")
        self.log.grid(row=0, column=0, sticky="nsew")
        
        log_toolbar = ttk.Frame(log_frame)
        log_toolbar.grid(row=1, column=0, sticky="ew", pady=(5,0))
        self.btn_clear_log = ttk.Button(log_toolbar, text="Limpiar", command=self._clear_log)
        self.btn_clear_log.pack(side="right")
        self.btn_open_output = ttk.Button(log_toolbar, text="Abrir Carpeta de Salida", command=self._open_output_folder, state="disabled")
        self.btn_open_output.pack(side="left")

    def _select_folder(self):
        path = filedialog.askdirectory(title="Selecciona la carpeta del proyecto")
        if path:
            self.project_path.set(path)
            self.selected_paths = set()
            self._update_sel_label()
            self._save_config()

    def _on_preset_change(self):
        # Toma SOLO la parte antes del paréntesis (si lo hay)
        raw = self.preset_var.get()
        expr = raw.split(" (", 1)[0].strip()
        self.exts_var.set(expr)
        self._save_config()

    def _show_exts_help(self):
        help_text = (
            "Formato del filtro de extensiones:\n\n"
            "• Inclusión: .py,.md\n"
            "    Convierte SOLO esas extensiones.\n\n"
            "• Exclusión: !pdf,!jpg\n"
            "    Convierte TODO excepto esas extensiones.\n\n"
            "• Mixto: .py,.md,!pdf\n"
            "    Convierte solo .py/.md y, además, excluye .pdf.\n\n"
            "• Todo: *\n"
            "    Convierte todas las extensiones.\n\n"
            "Ejemplos útiles:\n"
            "  - !pdf,!jpg,!png              → Todo excepto imágenes/PDF\n"
            "  - .json,.yml,.yaml,!lock      → Configs, excluye archivos *lock\n"
            "  - .ipynb,.py,!png,!jpg        → Notebooks + Py, sin imágenes"
        )

        win = tk.Toplevel(self.root)
        win.title("Ayuda: Filtro de extensiones")
        win.transient(self.root)          # flotante sobre la ventana principal
        win.grab_set()                    # modal
        win.resizable(False, False)

        # tamaño/posicionado cómodo
        pad = 14
        frm = ttk.Frame(win, padding=pad)
        frm.grid(sticky="nsew")
        frm.columnconfigure(0, weight=1)

        lbl = ttk.Label(frm, text=help_text, justify="left", wraplength=460)
        lbl.grid(row=0, column=0, sticky="w")

        btn = ttk.Button(frm, text="Cerrar", command=win.destroy, style="Accent.TButton")
        btn.grid(row=1, column=0, sticky="e", pady=(pad//2, 0))

        # Cerrar con ESC y Enter
        win.bind("<Escape>", lambda e: win.destroy())
        win.bind("<Return>", lambda e: win.destroy())

        # centrar sobre la ventana principal
        win.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - win.winfo_width()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - win.winfo_height()) // 3
        win.geometry(f"+{max(x,0)}+{max(y,0)}")

        # foco al botón
        btn.focus_set()

            
    def _open_selector(self):
        base_str = self.project_path.get()
        if not base_str or not Path(base_str).is_dir():
            messagebox.showerror("Error", "Debes seleccionar una carpeta válida primero.")
            return
        dlg = CheckTreeDialog(self.root, Path(base_str), self.selected_paths)
        self.root.wait_window(dlg)
        if dlg.result is not None:
            self.selected_paths = dlg.result
            self._update_sel_label()

    def _update_sel_label(self):
        if not self.selected_paths:
            self.lbl_sel.configure(text="(Actualmente: todo)")
        else:
            n = len(self.selected_paths)
            self.lbl_sel.configure(text=f"({n} elemento{'s' if n != 1 else ''} seleccionado{'s' if n != 1 else ''})")

    def _handle_drop(self, event):
        path_str = event.data.strip('{}')
        path = Path(path_str)
        if path.is_dir():
            self.project_path.set(str(path))
            self._save_config()
            self._log(f"Carpeta '{path.name}' seleccionada por Drag & Drop.")
        else:
            messagebox.showwarning("Entrada no válida", "Por favor, arrastra y suelta una carpeta, no un archivo.")
    
    def _clear_log(self):
        self.log.configure(state="normal")
        self.log.delete('1.0', tk.END)
        self.log.configure(state="disabled")

    def _open_output_folder(self):
        if self.last_output_path and self.last_output_path.parent.exists():
            webbrowser.open(self.last_output_path.parent.resolve())

    def _run_conversion(self):
        if not self.project_path.get():
            messagebox.showerror("Error", "Debes seleccionar una carpeta de proyecto.")
            return
        self._toggle_controls(False)
        self._clear_log()
        self._log("Iniciando conversión...")
        self.progress_bar["value"] = 0
        self.last_output_path = None
        self.btn_open_output.configure(state="disabled")
        threading.Thread(target=self._convert, daemon=True).start()

    def _convert(self):
        try:
            base = Path(self.project_path.get()).expanduser().resolve()
            name = self.output_name.get().strip() or "listado"
            fmt_idx = self.format_var.get()
            fmt = ("pdf", "txt", "csv")[fmt_idx]
            script_dir = Path(__file__).parent.resolve()
            output_path = script_dir / f"{name}.{fmt}"
            self.last_output_path = output_path

            self.log_queue.put(f"📂 Carpeta de origen: {base}")
            self.log_queue.put(f"💾 Archivo de salida: {output_path}")
            
            arbol, files = scan_project(base, self.selected_paths or None, self.log_queue)

            if not files:
                self.log_queue.put(("final_message", "showwarning", "No se encontraron archivos para convertir."))
                return

            # 👇 Nuevo: parsear extensiones
            allowed_exts = parse_exts(self.exts_var.get())  

            if fmt == "txt":
                export_txt(output_path, arbol, files, allowed_exts, self.log_queue) 
            else:
                self.log_queue.put(f"AVISO: La exportación a {fmt.upper()} no está implementada.")
                self.log_queue.put("-> Generando un archivo TXT de respaldo.")
                export_txt(output_path.with_suffix(".txt"), arbol, files, allowed_exts, self.log_queue)  

            self.log_queue.put(('progress', 100))
            self.log_queue.put("─" * 60)
            self.log_queue.put("✅ ¡Éxito! Conversión completada.")
            self.log_queue.put(("final_message", "showinfo", f"Archivo generado:\n{output_path}"))

        except Exception as exc:
            self.log_queue.put(("final_message", "showerror", f"❌ ERROR INESPERADO: {exc}"))
        finally:
            self.log_queue.put("END_PROCESS")


    def _process_log_queue(self):
        try:
            while True:
                msg = self.log_queue.get_nowait()
                if isinstance(msg, tuple):
                    if msg[0] == 'progress':
                        self.progress_bar["value"] = msg[1]
                    elif msg[0] == 'final_message':
                        _, msg_type, text = msg
                        if msg_type == 'showinfo': messagebox.showinfo("Éxito", text)
                        elif msg_type == 'showwarning': messagebox.showwarning("Aviso", text)
                        elif msg_type == 'showerror': messagebox.showerror("Error", text)
                elif msg == "END_PROCESS":
                    self._toggle_controls(True)
                    if self.last_output_path:
                        self.btn_open_output.configure(state="normal")
                else:
                    self._log(str(msg))
        except queue.Empty:
            pass
        self.root.after(100, self._process_log_queue)
        
    def _log(self, text: str):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _toggle_controls(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        for btn in [self.btn_browse, self.btn_selector, self.btn_convert, self.btn_clear_log]:
            btn.configure(state=state)
        for entry in [self.entry_path, self.entry_output]:
            entry.configure(state=state)
        for child in self.frm_fmt.winfo_children():
            child.configure(state=state)
    
    def _load_config(self):
        try:
            if self.CONFIG_FILE.exists():
                with open(self.CONFIG_FILE, "r") as f:
                    config = json.load(f)
                    
                    if last_path := config.get("last_project_path"):
                        if Path(last_path).exists():
                            self.project_path.set(last_path)
                            self._log(f"Cargada la última carpeta usada: {last_path}")
                    
                    theme = config.get("theme", "dark")
                    self.theme_var.set(theme)
                    sv_ttk.set_theme(theme)
                    self._log(f"Tema '{theme}' cargado.")
                    exts = config.get("exts", "*")
                    self.exts_var.set(exts)

                    preset = config.get("preset", "* (Todo)")
                    self.preset_var.set(preset)
            else:
                # Si no hay config, aplicar el tema por defecto que ya está en la variable
                sv_ttk.set_theme(self.theme_var.get())
        except Exception as e:
            # En caso de error, aplicar el tema por defecto para asegurar consistencia
            sv_ttk.set_theme(self.theme_var.get())
            self._log(f"No se pudo cargar la configuración: {e}")

    def _save_config(self):
        try:
            config = {
                "last_project_path": self.project_path.get(),
                "theme": self.theme_var.get(),
                "exts": self.exts_var.get(),
                "preset": self.preset_var.get(),
            }
            with open(self.CONFIG_FILE, "w") as f:
                json.dump(config, f, indent=2)
        except Exception as e:
            self._log(f"No se pudo guardar la configuración: {e}")
            
    def run(self):
        self.root.mainloop()

# ─────────────────────────────────────────────────────────────────────────────
#  ARRANQUE
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = ConvertidorGUI()
    app.run()