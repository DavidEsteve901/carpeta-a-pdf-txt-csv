# Convertidor universal (PDF / TXT / CSV)

> Herramienta de escritorio en **Python 3** que escanea cualquier carpeta y genera un único archivo PDF, TXT o CSV con el contenido de *todos* sus ficheros.
>
> * Sin dependencias gráficas externas: interfaz **Tkinter** incluida en la instalación estándar de Python.
> * Exportación opcional a **PDF** gracias a la librería [fpdf2](https://pypi.org/project/fpdf2/).
> * Compatible con Windows, macOS y Linux.

---

## 📦 Instalación

```bash
# Clona el repositorio
$ git clone https://github.com/<TU_USUARIO>/convertidor-universal.git
$ cd convertidor-universal

# (Opcional) Crea un entorno virtual
$ python -m venv .venv
$ source .venv/bin/activate  # en Windows: .venv\Scripts\activate

# Instala dependencias
$ python -m pip install -r requirements.txt  # sólo fpdf2 si quieres PDF
```

> **Nota:** Tkinter ya viene incluido con la mayoría de instaladores de Python. Si tu distribución de Linux lo separa, instala el paquete `python3-tk` desde tu gestor de paquetes.

---

## 🚀 Uso rápido

```bash
$ python convertidor_gui.py
```

1. **Selecciona la carpeta** que contiene los archivos a convertir.
2. Escribe el **nombre de salida** (sin extensión).
3. Elige el **formato** de exportación (pdf, txt o csv).
4. Pulsa **Convertir**.

Se creará `NOMBRE_SALIDA.<ext>` en el mismo directorio donde ejecutes el programa.

![Captura de pantalla](docs/screenshot.png)

---

## 🏗️ Construir un ejecutable (Windows)

```bash
$ python -m pip install pyinstaller
$ pyinstaller --onefile --noconsole convertidor_gui.py

# El ejecutable aparecerá en dist/convertidor_gui.exe
```

Para conservar la ventana de consola (útil al depurar), omite `--noconsole`.

---

## 📜 requirements.txt

```
fpdf2>=2.7   # Solo si vas a generar PDF
```

---

## 🗃️ Estructura del proyecto

```
convertidor-universal/
├── convertidor_gui.py   # Script principal con interfaz Tkinter
├── README.md            # Este documento
├── requirements.txt     # Dependencias (solo fpdf2)
└── docs/
    └── screenshot.png   # (opcional) imágenes para el README
```

---

## 📝 Licencia

Distribuido bajo licencia MIT. Consulta el archivo [LICENSE](LICENSE) para más información.

---

## 🙌 Créditos

* **fpdf2** – generación de PDF.
* Icono por [Font Awesome](https://fontawesome.com/).

---

## ⭐ Cómo contribuir

1. Haz un *fork* del proyecto.
2. Crea una rama (`git checkout -b feature/nueva-feature`).
3. Realiza tus cambios y haz *commit* (`git commit -m 'Añadir nueva feature'`).
4. *Push* a la rama (`git push origin feature/nueva-feature`).
5. Abre un *Pull Request*.
