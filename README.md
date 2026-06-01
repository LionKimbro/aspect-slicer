# Aspect Slicer

Tkinter/Pillow tool for managing print designs, importing source images, defining exact aspect-ratio crop rectangles, and exporting PNG slices for common print sizes.

## Run

```powershell
pip install -e .
aspect-slicer
```

The app stores local working data under `.aspect-slicer/` in the execution root.

## Test

```powershell
$env:PYTHONPATH="src"
python -m pytest -q
```
