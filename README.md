
# Convertidor Universal Pro (PDF / TXT / CSV)

> Herramienta de escritorio moderna en **Python 3** que escanea cualquier carpeta y genera un único archivo PDF, TXT o CSV con el contenido de *todos* sus ficheros.

Diseñada para ser potente y agradable de usar, esta versión incluye una **interfaz gráfica moderna** con temas claro/oscuro, soporte para **arrastrar y soltar**, una barra de progreso en tiempo real y mucho más.

*   **GUI Moderna**: Interfaz limpia y profesional gracias a `sv-ttk`.
*   **Modo Claro y Oscuro**: Cambia de tema al instante con un solo clic.
*   **Arrastrar y Soltar**: Selecciona carpetas simplemente arrastrándolas a la ventana.
*   **Feedback Visual**: Una barra de progreso te mantiene informado durante conversiones largas.
*   **Multiplataforma**: Compatible con Windows, macOS y Linux.
*   **Exportación a PDF**: Gracias a la potente librería [fpdf2](https://pypi.org/project/fpdf2/).

---

## 📦 Instalación

```bash
# Clona el repositorio
$ git clone https://github.com/<TU_USUARIO>/convertidor-universal.git
$ cd convertidor-universal

# (Recomendado) Crea un entorno virtual
$ python -m venv .venv
$ source .venv/bin/activate  # en Windows: .venv\Scripts\activate

# Instala todas las dependencias
$ python -m pip install -r requirements.txt
```

> **Nota:** Tkinter ya viene incluido con la mayoría de instaladores de Python. Si tu distribución de Linux lo separa, instala el paquete `python3-tk` desde tu gestor de paquetes (ej: `sudo apt-get install python3-tk`).

---

## 🚀 Uso rápido

```bash
$ python convertidor_gui_pro.py  # o el nombre que le hayas dado al script
```

1.  **Selecciona la carpeta** usando el botón "Examinar" o simplemente **arrastrándola y soltándola** sobre la ventana.
2.  Escribe el **nombre de salida** (sin extensión).
3.  Elige el **formato** de exportación (PDF, TXT o CSV).
4.  (Opcional) Usa el interruptor superior para cambiar entre **modo claro y oscuro**.
5.  Pulsa **Convertir**.

El archivo generado aparecerá en el mismo directorio donde ejecutes el programa. Un nuevo botón te permitirá **abrir la carpeta de salida** directamente.

<!-- TODO: Reemplazar con una captura de la nueva interfaz Pro -->
![Captura de pantalla](docs/screenshot-pro.png)

---

## 🏗️ Construir un ejecutable (Windows)

Para empaquetar la aplicación en un único archivo `.exe`, necesitas `pyinstaller` y asegurarte de que los recursos visuales de `sv-ttk` se incluyan correctamente.

```bash
# 1. Instala PyInstaller
$ python -m pip install pyinstaller

# 2. Encuentra la ruta de los temas de sv-ttk
#    Ejecuta este comando y copia la ruta que te muestra
$ python -c "import sv_ttk; print(sv_ttk.get_theme_root())"

# 3. Construye el ejecutable (reemplaza <RUTA_A_LOS_TEMAS> por la que copiaste)
#    En Windows, la ruta podría necesitar comillas y usar `\` como separador.
$ pyinstaller --onefile --noconsole --add-data "<RUTA_A_LOS_TEMAS>;sv_ttk/theme" convertidor_gui_pro.py```

*   **Ejemplo del comando final en Windows:**
    `pyinstaller --onefile --noconsole --add-data "C:\Users\TuUser\.venv\Lib\site-packages\sv_ttk\theme;sv_ttk/theme" convertidor_gui_pro.py`

El ejecutable final aparecerá en la carpeta `dist/`.

---

## 🗃️ Estructura del proyecto

```
convertidor-universal/
├── convertidor_gui_pro.py  # Script principal con la nueva interfaz
├── README.md               # Este documento
├── requirements.txt        # Dependencias del proyecto
└── docs/
    └── screenshot-pro.png  # (opcional) captura de la nueva interfaz
```

---

## 📝 Licencia

Distribuido bajo licencia MIT.

---

## 🙌 Créditos

*   **fpdf2**: Para la generación de archivos PDF.
*   **sv-ttk**: Para los excelentes temas visuales modernos.
*   **tkinterdnd2**: Para la funcionalidad de arrastrar y soltar.
*   **Iconos**: Por [Font Awesome](https://fontawesome.com/).

---

## ⭐ Cómo contribuir

1.  Haz un *fork* del proyecto.
2.  Crea una rama (`git checkout -b feature/nueva-feature`).
3.  Realiza tus cambios y haz *commit* (`git commit -m 'Añadir nueva feature'`).
4.  *Push* a la rama (`git push origin feature/nueva-feature`).
5.  Abre un *Pull Request*.