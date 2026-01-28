# -*- coding: utf-8 -*-
"""
Convertidor Universal Pro - V6 (Estructura Fantasma + Notificaciones)
=====================================================================
Nuevas Características:
1. Notificación emergente al finalizar.
2. Checkbox "Incluir estructura de no seleccionados":
   - Activado: Los archivos desmarcados aparecen en el índice (árbol) pero NO su código.
   - Desactivado: Los archivos desmarcados desaparecen totalmente.
3. Los archivos en "Ignorar" (node_modules) siempre desaparecen totalmente.
"""
from __future__ import annotations

import json
import queue
import threading
import webbrowser
import fnmatch
from pathlib import Path
from tkinter import filedialog, messagebox, ttk, scrolledtext, IntVar, StringVar, BooleanVar
import tkinter as tk

# Dependencias externas
import sv_ttk
from tkinterdnd2 import DND_FILES, TkinterDnD

# ─────────────────────────────────────────────────────────────────────────────
#  PRESETS
# ─────────────────────────────────────────────────────────────────────────────
IGNORE_PRESETS = {
    "Por defecto (General)": 
        "node_modules, .git, .svn, .hg, .idea, .vscode, .DS_Store, thumbs.db, __pycache__",
    "Desarrollo Web (Node/Frontend)": 
        "node_modules, .git, .vscode, dist, build, coverage, .next, .nuxt, package-lock.json, yarn.lock, .DS_Store",
    "Python (Backend/Data)": 
        "__pycache__, venv, .venv, env, .git, .vscode, *.pyc, *.pyd, poetry.lock, .ipynb_checkpoints, site-packages",
    "Agresivo (Solo código fuente)": 
        "node_modules, venv, .git, dist, build, *.lock, *.json, *.svg, *.png, *.jpg, *.pdf, *.zip, test, tests, docs, assets",
}

# ─────────────────────────────────────────────────────────────────────────────
#  SELECTOR DE ÁRBOL (CheckTreeDialog - Estable V5)
# ─────────────────────────────────────────────────────────────────────────────
class CheckTreeDialog(tk.Toplevel):
    def __init__(self, master, root_path: Path, preselected: set[Path] | None = None):
        super().__init__(master)
        self.title("Selector de Archivos")
        self.geometry("600x650")
        self.root_path = root_path.resolve()
        self.preselected = {p.resolve() for p in (preselected or [])}
        self.result = None
        self.checked = {}; self.item_paths = {}; self.loaded = set()
        self._setup_ui(); self._setup_root()
        self.transient(master); self.grab_set(); self.focus_set()

    def _setup_ui(self):
        self.columnconfigure(0, weight=1); self.rowconfigure(0, weight=1)
        frame = ttk.Frame(self, padding=10); frame.grid(sticky="nsew")
        frame.columnconfigure(0, weight=1); frame.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(frame, selectmode="browse")
        self.tree.grid(row=0, column=0, sticky="nsew")
        ysb = ttk.Scrollbar(frame, command=self.tree.yview); ysb.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=ysb.set)
        btn_frame = ttk.Frame(frame); btn_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10,0))
        ttk.Button(btn_frame, text="Marcar Todo", command=self._select_all).pack(side="left")
        ttk.Button(btn_frame, text="Desmarcar Todo", command=self._deselect_all).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="Guardar y Cerrar", style="Accent.TButton", command=self._save).pack(side="right")
        ttk.Button(btn_frame, text="Cancelar", command=self.destroy).pack(side="right", padx=5)
        self.tree.bind("<<TreeviewOpen>>", self._on_expand)
        self.tree.bind("<Button-1>", self._on_click)

    def _setup_root(self):
        root_iid = self.tree.insert("", "end", text=f" {self.root_path.name}", open=True)
        self.item_paths[root_iid] = self.root_path
        if not self.preselected or self.root_path in self.preselected: self._set_state(root_iid, "checked")
        else: self._set_state(root_iid, "unchecked")
        self._load_children(root_iid)

    def _load_children(self, parent_iid):
        if parent_iid in self.loaded: return
        children = self.tree.get_children(parent_iid)
        if children and children[0] not in self.item_paths: self.tree.delete(children[0])
        parent_path = self.item_paths[parent_iid]
        parent_state = self.checked.get(parent_iid, "unchecked")
        try:
            entries = sorted(parent_path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
            for path in entries:
                is_dir = path.is_dir()
                display = f" {path.name}/" if is_dir else f" {path.name}"
                iid = self.tree.insert(parent_iid, "end", text=display, open=False)
                self.item_paths[iid] = path
                state = "checked" if (path in self.preselected or parent_state == "checked") else "unchecked"
                self._set_state(iid, state)
                if is_dir: self.tree.insert(iid, "end", text="loading...")
            self.loaded.add(parent_iid)
        except: pass

    def _on_expand(self, event):
        sel = self.tree.selection()
        if sel: self._load_children(sel[0])

    def _on_click(self, event):
        iid = self.tree.identify_row(event.y)
        if iid and self.tree.identify_region(event.x, event.y) == "tree": self._toggle(iid)

    def _set_state(self, iid, state):
        self.checked[iid] = state
        icon = "☑" if state == "checked" else "☐"
        raw_text = self.tree.item(iid, "text").replace("☑", "").replace("☐", "").strip()
        self.tree.item(iid, text=f"{icon} {raw_text}")

    def _toggle(self, iid):
        new = "unchecked" if self.checked.get(iid, "unchecked") == "checked" else "checked"
        self._set_state(iid, new)
        for child in self.tree.get_children(iid): self._propagate_down(child, new)
        p = self.tree.parent(iid)
        if p: self._update_parent_up(p)

    def _propagate_down(self, iid, state):
        self._set_state(iid, state)
        for child in self.tree.get_children(iid): self._propagate_down(child, state)

    def _update_parent_up(self, iid):
        children = self.tree.get_children(iid)
        if not children: return
        new_state = "checked" if all(self.checked.get(c) == "checked" for c in children) else "unchecked"
        if self.checked.get(iid) != new_state:
            self._set_state(iid, new_state)
            p = self.tree.parent(iid)
            if p: self._update_parent_up(p)

    def _select_all(self):
        for i in self.item_paths:
            if not self.tree.parent(i): self._toggle_root(i, "checked")
    def _deselect_all(self):
        for i in self.item_paths:
            if not self.tree.parent(i): self._toggle_root(i, "unchecked")
    def _toggle_root(self, iid, s):
        self._set_state(iid, s)
        for c in self.tree.get_children(iid): self._propagate_down(c, s)
    def _save(self):
        self.result = {p for i, p in self.item_paths.items() if self.checked.get(i) == "checked"}
        self.destroy()

# ─────────────────────────────────────────────────────────────────────────────
#  LÓGICA CENTRAL
# ─────────────────────────────────────────────────────────────────────────────

def read_file_safe(path: Path) -> list[str]:
    try: return path.read_text("utf-8").splitlines(True)
    except:
        try: return path.read_text("latin-1").splitlines(True)
        except: return ["[ERROR LECTURA]"]

def is_ignored(path: Path, base: Path, ignores: list[str]) -> bool:
    """Verifica si el archivo está en la lista negra (node_modules, etc)."""
    if not ignores: return False
    try: rel = path.relative_to(base)
    except: rel = path
    
    # Nombre exacto o patrón
    if any(fnmatch.fnmatch(path.name, p) for p in ignores): return True
    # Carpeta padre prohibida
    for part in rel.parts:
        if any(fnmatch.fnmatch(part, p) for p in ignores): return True
    return False

def scan_process(base: Path, selected: set[Path] | None, ignores: list, include_ghosts: bool, q: queue.Queue):
    tree, files = {}, []
    sel_resolved = {p.resolve() for p in selected} if selected else None
    
    q.put(f"-> Escaneando: {base}")
    all_files = list(base.rglob("*"))
    total = len(all_files)
    
    def is_selected(p: Path):
        if not sel_resolved: return True
        p_abs = p.resolve()
        for s in sel_resolved:
            if p_abs == s or s in p_abs.parents: return True
        return False

    processed = 0
    for i, path in enumerate(all_files):
        if i % 200 == 0: q.put(('prog', (i/total)*20))
        if not path.is_file(): continue
        
        # 1. FILTRO DE IGNORADOS (Blacklist absoluta)
        # Si está aquí (ej. node_modules), NO sale ni en estructura ni en contenido.
        if is_ignored(path, base, ignores): continue
        
        # 2. FILTRO DE SELECCIÓN
        selected_flag = is_selected(path)
        
        # Lógica:
        # - Si está seleccionado -> Va a estructura Y contenido.
        # - Si NO está seleccionado pero include_ghosts=True -> Va a estructura, NO contenido.
        # - Si NO está seleccionado y include_ghosts=False -> Se ignora totalmente.
        
        if not selected_flag and not include_ghosts:
            continue
            
        rel = path.relative_to(base)
        
        # Agregar al ÁRBOL (Estructura)
        curr = tree
        for part in rel.parent.parts:
            curr = curr.setdefault(part, {})
        curr.setdefault("__files__", []).append(rel.name)
        
        # Agregar al CONTENIDO (Solo si está seleccionado explícitamente)
        if selected_flag:
            files.append((rel, read_file_safe(path)))
            processed += 1
        
    q.put(f"-> Fin escaneo. {processed} archivos con contenido.")
    return tree, files

def export_data(path: Path, tree: dict, files: list, ext_filter: tuple, q: queue.Queue):
    q.put("-> Escribiendo reporte...")
    
    def valid_ext(p):
        if not ext_filter: return True
        inc, exc = ext_filter
        ext = p.suffix.lower()
        if inc and ext not in inc: return False
        if ext in exc: return False
        return True

    def write_tree(node, indent=0):
        lines = []
        for k, v in sorted(node.items()):
            if k == "__files__":
                for f in sorted(v): lines.append(" " * indent + f"- {f}")
            else:
                lines.append(" " * indent + f"[{k}]/")
                lines.extend(write_tree(v, indent + 4))
        return lines

    with path.open("w", encoding="utf-8") as f:
        f.write("# ESTRUCTURA DEL PROYECTO\n")
        f.write("# (Incluye archivos sin contenido si se configuró así)\n\n")
        f.write("\n".join(write_tree(tree)) + "\n\n")
        
        f.write("# CONTENIDO DE ARCHIVOS\n\n")
        
        count = 0
        for i, (rel, content) in enumerate(files):
            if i % 50 == 0: q.put(('prog', 20 + (i/len(files))*80))
            if valid_ext(rel):
                f.write(f"## {rel}\n```\n{''.join(content)}\n```\n\n")
                count += 1
                
    q.put(f"-> Archivo guardado. {count} bloques de código generados.")

# ─────────────────────────────────────────────────────────────────────────────
#  GUI
# ─────────────────────────────────────────────────────────────────────────────
class App:
    CFG = Path.home() / ".convertidor_pro_v6.json"
    
    def __init__(self):
        self.root = TkinterDnD.Tk()
        self.root.title("Convertidor Universal Pro - V6")
        self.root.geometry("950x850")
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        
        # Variables
        self.v_path = StringVar()
        self.v_out = StringVar(value="contexto")
        self.v_theme = StringVar(value="dark")
        self.v_ext_preset = StringVar(value="* (Todo)")
        self.v_ext_manual = StringVar(value="*")
        self.v_ign_preset = StringVar(value="Por defecto (General)")
        self.v_ghost_structure = BooleanVar(value=True) # Nueva variable
        
        self.sel_paths = set()
        self.q = queue.Queue()
        self.last_out = None
        
        self.build_ui()
        self.load_cfg()
        self.loop_q()
        
        self.entry_path.drop_target_register(DND_FILES)
        self.entry_path.dnd_bind('<<Drop>>', lambda e: self.v_path.set(e.data.strip('{}')))

    def build_ui(self):
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(3, weight=1)
        
        # Header
        f1 = ttk.Frame(self.root, padding=10)
        f1.grid(row=0, sticky="ew")
        f1.columnconfigure(1, weight=1)
        ttk.Label(f1, text="Proyecto:").grid(row=0, column=0)
        self.entry_path = ttk.Entry(f1, textvariable=self.v_path)
        self.entry_path.grid(row=0, column=1, sticky="ew", padx=5)
        ttk.Button(f1, text="Examinar", command=self.ask_dir).grid(row=0, column=2)
        ttk.Checkbutton(f1, text="Dark", style="Switch.TCheckbutton", variable=self.v_theme, 
                       onvalue="dark", offvalue="light", command=self.set_theme).grid(row=0, column=3, padx=10)

        # Settings
        f2 = ttk.Frame(self.root, padding=(10,0))
        f2.grid(row=1, sticky="nsew")
        f2.columnconfigure(1, weight=1)
        
        # Left Panel
        left = ttk.Frame(f2)
        left.grid(row=0, column=0, sticky="nsew", padx=(0,5))
        
        lf1 = ttk.LabelFrame(left, text="Salida", padding=5)
        lf1.pack(fill="x")
        ttk.Entry(lf1, textvariable=self.v_out).pack(fill="x")
        
        lf2 = ttk.LabelFrame(left, text="Selección Árbol", padding=5)
        lf2.pack(fill="x", pady=5)
        ttk.Button(lf2, text="Abrir Selector", command=self.open_tree).pack(fill="x")
        self.lbl_tree = ttk.Label(lf2, text="(Todo)", foreground="gray")
        self.lbl_tree.pack()
        
        # Checkbox "Estructura Fantasma"
        ttk.Checkbutton(lf2, text="Incluir estructura de no seleccionados", 
                       variable=self.v_ghost_structure).pack(fill="x", pady=(5,0))
        ttk.Label(lf2, text="(Aparecen en índice, pero sin código)", font=("Segoe UI", 7, "italic")).pack()

        # Right Panel
        right = ttk.Frame(f2)
        right.grid(row=0, column=1, sticky="nsew")
        rf = ttk.LabelFrame(right, text="Filtros & Ignorados", padding=5)
        rf.pack(fill="both", expand=True)
        
        ttk.Label(rf, text="Extensiones:").pack(anchor="w")
        cb = ttk.Combobox(rf, textvariable=self.v_ext_preset, values=[
            "* (Todo)", ".py,.js,.ts,.html,.css", ".c,.cpp,.h", "!pdf,!jpg,!png", ".md,.txt"
        ])
        cb.pack(fill="x")
        cb.bind("<<ComboboxSelected>>", lambda e: self.v_ext_manual.set(self.v_ext_preset.get().split(' (')[0]))
        ttk.Entry(rf, textvariable=self.v_ext_manual).pack(fill="x", pady=2)
        
        ttk.Separator(rf).pack(fill="x", pady=5)
        ttk.Label(rf, text="Ignorar (Desaparecen totalmente):", foreground="#e06c75").pack(anchor="w")
        cb2 = ttk.Combobox(rf, textvariable=self.v_ign_preset, values=list(IGNORE_PRESETS.keys()))
        cb2.pack(fill="x")
        cb2.bind("<<ComboboxSelected>>", lambda e: self.set_ignore_txt(IGNORE_PRESETS.get(self.v_ign_preset.get())))
        self.txt_ign = scrolledtext.ScrolledText(rf, height=6, font=("Consolas",9))
        self.txt_ign.pack(fill="both", expand=True, pady=2)

        # Actions
        f3 = ttk.Frame(self.root, padding=10)
        f3.grid(row=2, sticky="ew")
        f3.columnconfigure(0, weight=1)
        self.btn_run = ttk.Button(f3, text="GENERAR CONTEXTO", style="Accent.TButton", command=self.run)
        self.btn_run.grid(row=0, sticky="ew")
        self.pb = ttk.Progressbar(f3)
        self.pb.grid(row=1, sticky="ew", pady=5)

        # Log
        f4 = ttk.LabelFrame(self.root, text="Log", padding=5)
        f4.grid(row=3, sticky="nsew", padx=10, pady=5)
        f4.columnconfigure(0, weight=1); f4.rowconfigure(0, weight=1)
        self.log = scrolledtext.ScrolledText(f4, state="disabled", height=6, font=("Consolas",9))
        self.log.grid(row=0, sticky="nsew")
        btns = ttk.Frame(f4); btns.grid(row=1, sticky="ew")
        self.btn_opn = ttk.Button(btns, text="Abrir Carpeta", state="disabled", command=lambda: webbrowser.open(self.last_out.parent))
        self.btn_opn.pack(side="left")

    # ──────────────── LOGIC ────────────────
    def ask_dir(self):
        d = filedialog.askdirectory()
        if d: 
            self.v_path.set(d)
            self.sel_paths = set()
            self.update_lbl()

    def open_tree(self):
        if not self.v_path.get(): return
        dlg = CheckTreeDialog(self.root, Path(self.v_path.get()), self.sel_paths)
        self.root.wait_window(dlg)
        if dlg.result is not None:
            self.sel_paths = dlg.result
            self.update_lbl()

    def update_lbl(self):
        n = len(self.sel_paths)
        self.lbl_tree.config(text=f"({n} seleccionados)" if n > 0 else "(Todo)")

    def set_ignore_txt(self, t):
        self.txt_ign.delete("1.0", "end")
        self.txt_ign.insert("1.0", t)
    def set_theme(self): sv_ttk.set_theme(self.v_theme.get())

    def log_msg(self, t):
        self.log.config(state="normal")
        self.log.insert("end", str(t)+"\n")
        self.log.see("end")
        self.log.config(state="disabled")

    def loop_q(self):
        try:
            while True:
                m = self.q.get_nowait()
                if isinstance(m, tuple):
                    if m[0]=='prog': self.pb['value'] = m[1]
                    elif m[0]=='msg':
                        # Mostrar popup en hilo principal
                        if m[1]=='info': messagebox.showinfo("Información", m[2])
                        elif m[1]=='err': messagebox.showerror("Error", m[2])
                elif m == 'END':
                    self.btn_run.config(state="normal")
                    if self.last_out: self.btn_opn.config(state="normal")
                elif m == 'DONE': self.pb['value'] = 100
                else: self.log_msg(m)
        except queue.Empty: pass
        self.root.after(100, self.loop_q)

    def run(self):
        if not self.v_path.get(): return
        self.save_cfg()
        self.btn_run.config(state="disabled")
        self.log.config(state="normal"); self.log.delete("1.0","end"); self.log.config(state="disabled")
        self.pb['value'] = 0
        threading.Thread(target=self.worker, daemon=True).start()

    def worker(self):
        try:
            base = Path(self.v_path.get())
            ign_txt = self.txt_ign.get("1.0", "end").replace("\n", ",")
            ignores = [x.strip() for x in ign_txt.split(",") if x.strip()]
            ghosts = self.v_ghost_structure.get()
            
            tree, files = scan_process(base, self.sel_paths, ignores, ghosts, self.q)
            
            out = Path(__file__).parent / (self.v_out.get().strip() + ".txt")
            self.last_out = out
            
            exts = None
            raw_ext = self.v_ext_manual.get().strip()
            if raw_ext and raw_ext not in ["*", "todos"]:
                inc, exc = set(), set()
                for p in raw_ext.split(","):
                    if p.startswith("!"): exc.add("."+p[1:].lstrip("."))
                    else: inc.add("."+p.lstrip("."))
                if inc or exc: exts = (inc, exc)

            export_data(out, tree, files, exts, self.q)
            self.q.put("DONE")
            self.q.put(("msg", "info", f"✅ Proceso terminado.\nArchivo generado: {out.name}"))
            
        except Exception as e:
            self.q.put(f"❌ Error: {e}")
            self.q.put(("msg", "err", str(e)))
        finally: self.q.put("END")

    def save_cfg(self):
        d = {
            "path": self.v_path.get(),
            "theme": self.v_theme.get(),
            "exts": self.v_ext_manual.get(),
            "ign_txt": self.txt_ign.get("1.0", "end-1c"),
            "ign_pre": self.v_ign_preset.get(),
            "ghost": self.v_ghost_structure.get()
        }
        try: self.CFG.write_text(json.dumps(d))
        except: pass

    def load_cfg(self):
        try:
            if self.CFG.exists():
                d = json.loads(self.CFG.read_text())
                self.v_path.set(d.get("path",""))
                self.v_theme.set(d.get("theme","dark"))
                self.v_ext_manual.set(d.get("exts","*"))
                self.v_ign_preset.set(d.get("ign_pre","Por defecto"))
                self.set_ignore_txt(d.get("ign_txt", IGNORE_PRESETS["Por defecto (General)"]))
                self.v_ghost_structure.set(d.get("ghost", True))
                self.set_theme()
            else:
                self.set_theme()
                self.set_ignore_txt(IGNORE_PRESETS["Por defecto (General)"])
        except: pass

    def on_close(self):
        self.save_cfg()
        self.root.destroy()

if __name__ == "__main__":
    App().root.mainloop()