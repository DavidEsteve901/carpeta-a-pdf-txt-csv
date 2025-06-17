#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Convertidor universal con interfaz Tkinter
=========================================
Convierte *todo* el contenido de un directorio (no filtra por extensión) a:
    • **PDF** – índice + contenido por archivo (requiere `fpdf2`)
    • **TXT** – índice + contenido
    • **CSV** – columnas: ruta, nº línea, contenido

Instalación rápida:
    python -m pip install fpdf2   # sólo si necesitas PDF

Cómo ejecutar:
    python convertidor_gui.py

Empaquetar a .EXE (Windows):
    python -m pip install pyinstaller
    pyinstaller --onefile --noconsole convertidor_gui.py

La GUI se construye únicamente con Tkinter (incluido en la instalación estándar
  de Python), por lo que no dependemos de PySimpleGUI ni de servidores
  privados.
"""

from __future__ import annotations

import csv
import os
import threading
from pathlib import Path
from tkinter import filedialog, messagebox, ttk, scrolledtext, IntVar, StringVar, Tk

# ─────────────────────────────────────────────────────────────────────────────
#  Dependencia opcional para PDF
# ─────────────────────────────────────────────────────────────────────────────
try:
    from fpdf import FPDF  # type: ignore
except ImportError:  # pragma: no cover
    FPDF = None

# ─────────────────────────────────────────────────────────────────────────────
#  Lógica de negocio (reutilizada de tu script original)
# ─────────────────────────────────────────────────────────────────────────────

def scan_project(base: Path):
    """Devuelve `(arbol, files)` donde:
    - *arbol* es un dict recursivo que representa carpetas y archivos.
    - *files* es una lista `[ (ruta_relativa, [líneas]), … ]`"""
    arbol: dict[str, dict] = {}
    files: list[tuple[Path, list[str]]] = []

    for root, _, filenames in os.walk(base):
        rel_root = Path(root).relative_to(base)
        nodo = arbol
        if rel_root != Path('.'):
            for parte in rel_root.parts:
                nodo = nodo.setdefault(parte, {})  # type: ignore[arg-type]

        for name in filenames:
            nodo.setdefault('__files__', []).append(name)  # type: ignore[arg-type]
            ruta = Path(root) / name
            try:
                with ruta.open('r', encoding='utf-8', errors='ignore') as fh:
                    files.append((ruta.relative_to(base), fh.readlines()))
            except Exception as exc:  # pragma: no cover
                print(f'⚠️  No se pudo leer {ruta}: {exc}')

    return arbol, files


def _tree_txt(nodo: dict, indent: int = 0):
    for k, v in sorted(nodo.items()):
        if k == '__files__':
            for f in sorted(v):
                yield ' ' * indent + f'- {f}'
        else:
            yield ' ' * indent + f'[{k}]/'
            yield from _tree_txt(v, indent + 4)


def export_txt(output: Path, arbol: dict, files: list[tuple[Path, list[str]]]):
    with output.open('w', encoding='utf-8') as fh:
        fh.write('# Árbol de archivos\n')
        fh.write('\n'.join(_tree_txt(arbol)))
        fh.write('\n\n# Contenido de archivos\n\n')
        for rel_path, lines in files:
            fh.write(f'## {rel_path}\n')
            fh.writelines(lines)
            fh.write('\n')


def export_csv(output: Path, files: list[tuple[Path, list[str]]]):
    with output.open('w', newline='', encoding='utf-8') as fh:
        writer = csv.writer(fh)
        writer.writerow(['path', 'line_no', 'content'])
        for rel_path, lines in files:
            for i, ln in enumerate(lines, 1):
                writer.writerow([str(rel_path), i, ln.rstrip('\n')])


def _draw_tree_pdf(pdf: 'FPDF', nodo: dict, indent: int = 0):  # noqa: F722
    for k, v in sorted(nodo.items()):
        if k == '__files__':
            for f in sorted(v):
                pdf.multi_cell(0, 5, ' ' * indent + f'- {f}', new_x='LMARGIN', new_y='NEXT')
        else:
            pdf.multi_cell(0, 5, ' ' * indent + f'[{k}]/', new_x='LMARGIN', new_y='NEXT')
            _draw_tree_pdf(pdf, v, indent + 4)


def export_pdf(base: Path, output: Path, arbol: dict, files: list[tuple[Path, list[str]]]):
    if FPDF is None:
        raise RuntimeError('Instala primero fpdf2 →  python -m pip install fpdf2')

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_font('Courier', size=10)

    # Portada con árbol
    pdf.add_page()
    pdf.set_font('Courier', style='B', size=12)
    pdf.multi_cell(0, 8, f'Resumen de archivos en:\n{base}\n', new_x='LMARGIN', new_y='NEXT')
    pdf.set_font('Courier', size=10)
    _draw_tree_pdf(pdf, arbol)

    # Contenido
    for rel_path, lines in files:
        pdf.add_page()
        pdf.set_font('Courier', style='B', size=11)
        pdf.multi_cell(0, 7, f'{rel_path}\n', new_x='LMARGIN', new_y='NEXT')
        pdf.set_font('Courier', size=9)
        for ln in lines:
            pdf.multi_cell(0, 5, ln.encode('latin-1', 'replace').decode('latin-1'), new_x='LMARGIN', new_y='NEXT')

    pdf.output(output)


# ─────────────────────────────────────────────────────────────────────────────
#  GUI con Tkinter
# ─────────────────────────────────────────────────────────────────────────────

class ConvertidorGUI:
    def __init__(self) -> None:
        self.root = Tk()
        self.root.title('Convertidor universal (PDF / TXT / CSV)')
        self.root.geometry('600x400')

        self.project_path = StringVar()
        self.output_name = StringVar(value='listado')
        self.format_var = IntVar(value=0)  # 0 = PDF, 1 = TXT, 2 = CSV

        self._build_layout()

    # ---------------------------------------------------------------------
    #  Construcción de la interfaz
    # ---------------------------------------------------------------------
    def _build_layout(self):
        padding = {'padx': 8, 'pady': 4}

        # Selección de carpeta
        frm_top = ttk.Frame(self.root)
        frm_top.pack(fill='x', **padding)

        ttk.Label(frm_top, text='Carpeta del proyecto:').pack(side='left')
        ttk.Entry(frm_top, textvariable=self.project_path, width=50).pack(side='left', padx=(4, 0))
        ttk.Button(frm_top, text='Examinar…', command=self._select_folder).pack(side='left', padx=4)

        # Nombre del fichero de salida
        frm_out = ttk.Frame(self.root)
        frm_out.pack(fill='x', **padding)
        ttk.Label(frm_out, text='Nombre de salida (sin extensión):').pack(side='left')
        ttk.Entry(frm_out, textvariable=self.output_name, width=30).pack(side='left', padx=(4, 0))

        # Formato
        frm_fmt = ttk.LabelFrame(self.root, text='Formato')
        frm_fmt.pack(fill='x', **padding)
        ttk.Radiobutton(frm_fmt, text='PDF', variable=self.format_var, value=0).pack(side='left', padx=10)
        ttk.Radiobutton(frm_fmt, text='TXT', variable=self.format_var, value=1).pack(side='left', padx=10)
        ttk.Radiobutton(frm_fmt, text='CSV', variable=self.format_var, value=2).pack(side='left', padx=10)

        # Botón ejecutar
        ttk.Button(self.root, text='Convertir', command=self._run_conversion).pack(**padding)

        # Área de log
        self.log = scrolledtext.ScrolledText(self.root, height=10, state='disabled', font=('Consolas', 9))
        self.log.pack(fill='both', expand=True, **padding)

    # ------------------------------------------------------------------
    #  Callbacks
    # ------------------------------------------------------------------
    def _select_folder(self):
        path = filedialog.askdirectory(title='Selecciona la carpeta del proyecto')
        if path:
            self.project_path.set(path)

    def _run_conversion(self):
        # Ejecutar en un thread para no congelar la GUI
        threading.Thread(target=self._convert, daemon=True).start()

    def _convert(self):
        base = Path(self.project_path.get()).expanduser().resolve()
        name = self.output_name.get().strip() or 'listado'
        fmt_idx = self.format_var.get()
        fmt = ('pdf', 'txt', 'csv')[fmt_idx]

        if not base.is_dir():
            messagebox.showerror('Error', 'Debes seleccionar una carpeta válida')
            return

        output = Path.cwd() / f'{name}.{fmt}'

        self._log(f'📂 Carpeta: {base}')
        self._log(f'💾 Salida : {output}')
        self._log(f'📄 Formato: {fmt.upper()}')
        self._log('──────────────────────────────────────────────────────')

        try:
            arbol, files = scan_project(base)
            if fmt == 'pdf':
                export_pdf(base, output, arbol, files)
            elif fmt == 'txt':
                export_txt(output, arbol, files)
            else:
                export_csv(output, files)
            self._log(f'✅ Conversión completada → {output}\n')
            messagebox.showinfo('Éxito', f'Archivo generado:\n{output}')
        except Exception as exc:
            self._log(f'❌ Error: {exc}\n')
            messagebox.showerror('Error', str(exc))

    def _log(self, text: str):
        self.log.configure(state='normal')
        self.log.insert('end', text + '\n')
        self.log.configure(state='disabled')
        self.log.see('end')

    # ------------------------------------------------------------------
    def run(self):
        self.root.mainloop()


# ─────────────────────────────────────────────────────────────────────────────
#  Arranque
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    gui = ConvertidorGUI()
    gui.run()
