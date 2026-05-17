# DICOM → Video Extractor

A production-grade desktop application that extracts pixel data from multi-frame DICOM files and writes standard video files (MP4 / AVI / MKV) while preserving frame rate and visual fidelity.

---

## Features

- Drag-and-drop or file-picker DICOM import
- Streaming frame extraction — never loads the full pixel array for large cine loops
- Correct handling of MONOCHROME1 (X-ray) polarity inversion
- Stable 16-bit to 8-bit mapping across frames (no flicker)
- MPEG/H.264 passthrough (zero re-encode for compatible files)
- Quality presets: Lossless, High, Compressed
- Output formats: MP4, AVI, MKV
- Dark-themed PyQt6 UI with per-file progress and log panel
- DICOM metadata viewer with PHI highlighting

---

## Supported Transfer Syntaxes

| UID | Name | Method |
|---|---|---|
| 1.2.840.10008.1.2 | Implicit VR Little Endian | pydicom native |
| 1.2.840.10008.1.2.1 | Explicit VR Little Endian | pydicom native |
| 1.2.840.10008.1.2.2 | Explicit VR Big Endian | pydicom native |
| 1.2.840.10008.1.2.5 | RLE Lossless | pylibjpeg-rle |
| 1.2.840.10008.1.2.4.50 | JPEG Baseline 8-bit | pylibjpeg-libjpeg |
| 1.2.840.10008.1.2.4.51 | JPEG Extended 12-bit | pylibjpeg-libjpeg |
| 1.2.840.10008.1.2.4.57/.70 | JPEG Lossless | pylibjpeg-libjpeg |
| 1.2.840.10008.1.2.4.80/.81 | JPEG-LS | pylibjpeg-libjpeg |
| 1.2.840.10008.1.2.4.90/.91 | JPEG 2000 | pylibjpeg-openjpeg |
| 1.2.840.10008.1.2.4.100/101 | MPEG2 | stream-copy passthrough |
| 1.2.840.10008.1.2.4.102/103 | MPEG-4 AVC/H.264 | stream-copy passthrough |
| 1.2.840.10008.1.2.4.107/108 | HEVC/H.265 | stream-copy passthrough |

---

## Requirements

- Python 3.11+
- FFmpeg (must be on `PATH`)

### Install FFmpeg

**Windows:**
```
winget install Gyan.FFmpeg
```
Or download from https://www.gyan.dev/ffmpeg/builds/ and add the `bin/` folder to your PATH.

**macOS:**
```
brew install ffmpeg
```

**Linux:**
```
sudo apt install ffmpeg        # Debian/Ubuntu
sudo dnf install ffmpeg        # Fedora
sudo pacman -S ffmpeg          # Arch
```

---

## Installation

```bash
git clone https://github.com/Isaackjoshua/DICOM.git
cd DICOM/dicom-video-extractor

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Or as an editable package
pip install -e .
```

---

## Running

```bash
python main.py
```

---

## Running Tests

```bash
pytest
```

To include the PyQt6 smoke test:
```bash
pytest --qt-api=pyqt6
```

---

## Troubleshooting

| Problem | Solution |
|---|---|
| "FFmpeg Not Found" dialog on startup | Install FFmpeg and ensure it is on your system PATH |
| `UnsupportedTransferSyntaxError` | Install `pylibjpeg` and all sub-packages; see requirements.txt |
| Blank / black frames | File may be MONOCHROME1 — check the log panel for inversion messages |
| Flickering brightness in output | Ensure you are not using `raw_mode`; windowing scalars must be computed once |
| Application hangs on large file | Streaming mode is enabled by default; check the log for OOM warnings |
| PyQt6 import error | Run `pip install PyQt6` inside your virtual environment |

---

## Project Structure

```
dicom-video-extractor/
├── main.py                   Entry point
├── src/
│   ├── core/                 DICOM reading, pixel pipeline, FPS resolver, video writer
│   ├── services/             Conversion orchestration, batch processing (Phase 3)
│   ├── ui/                   PyQt6 main window, worker thread, widgets
│   └── utils/                FFmpeg utilities, logging, custom exceptions
├── tests/                    pytest test suite
└── docs/                     Architecture and DICOM notes
```

---

## Changelog

See [CHANGELOG.md](CHANGELOG.md).
