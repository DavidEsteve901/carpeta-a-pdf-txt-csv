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
        self.root.title("Convertidor Universal Pro")
        self.root.geometry("850x650")
        self.root.minsize(700, 500)

        # Crear todas las variables de estado ANTES de cualquier otra cosa.
        self.project_path = StringVar()
        self.output_name = StringVar(value="listado")
        self.format_var = IntVar(value=1)
        self.theme_var = tk.StringVar(value="dark")
        self.selected_paths: set[Path] = set()
        self.last_output_path: Path | None = None
        self.log_queue = queue.Queue()
        
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

    def _select_folder(self):
        path = filedialog.askdirectory(title="Selecciona la carpeta del proyecto")
        if path:
            self.project_path.set(path)
            self.selected_paths = set()
            self._update_sel_label()
            self._save_config()
            
    def _open_selector(self):
        base_str = self.project_path.get()
        if not base_str or not Path(base_str).is_dir():
            messagebox.showerror("Error", "Debes seleccionar una carpeta válida primero.")
            return
        dlg = CheckTreeDialog(self.root, Path(base_str), self.selected_paths)
        self.root.wait_window(dlg)
        if dlg.result is not None:
            self.sel_paths = dlg.result
            self.update_lbl()

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
            output_path = Path.cwd() / f"{name}.{fmt}"
            self.last_output_path = output_path

            self.log_queue.put(f"📂 Carpeta de origen: {base}")
            self.log_queue.put(f"💾 Archivo de salida: {output_path}")
            
            arbol, files = scan_project(base, self.selected_paths or None, self.log_queue)

            if not files:
                self.log_queue.put(("final_message", "showwarning", "No se encontraron archivos para convertir."))
                return

            if fmt == "txt":
                export_txt(output_path, arbol, files, self.log_queue)
            else:
                self.log_queue.put(f"AVISO: La exportación a {fmt.upper()} no está implementada.")
                self.log_queue.put("-> Generando un archivo TXT de respaldo.")
                export_txt(output_path.with_suffix(".txt"), arbol, files, self.log_queue)

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
            else:
                # Si no hay config, aplicar el tema por defecto que ya está en la variable
                sv_ttk.set_theme(self.theme_var.get())
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
            config = {
                "last_project_path": self.project_path.get(),
                "theme": self.theme_var.get()
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
    App().root.mainloop()