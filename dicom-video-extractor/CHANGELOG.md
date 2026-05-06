# Changelog

## [Unreleased] — Phase 2 Real-world Robustness

### Added
- `utils/handlers.py` — pydicom handler priority (pylibjpeg → rle → numpy → gdcm) configured at startup
- `tests/test_frame_extractor.py` — frame extraction tests across uncompressed, RLE, JPEG/YBR transfer syntaxes
- `tests/test_integration.py` — end-to-end conversion tests (FFmpeg required): rtdose, YBR cine, RLE, cancellation, FPS match
- `tests/test_smoke_qt.py` — 8 pytest-qt smoke tests: window open, drag-drop, clear, invalid file, duplicate guard, metadata dialog

### Changed
- `frame_extractor.py` — rewritten on pydicom 3 `iter_pixels` API; handles all transfer syntaxes (JPEG, JPEG-LS, JPEG 2000, RLE, uncompressed Big/Little Endian, 32-bit RT dose); memory-safe via file-path input
- `pixel_pipeline.py` — added `photometric_override` param (avoids redundant YBR→RGB when iter_pixels already converted); updated imports to `pydicom.pixels`; added pixel aspect ratio correction (`_apply_pixel_spacing`); handles 32-bit uint arrays
- `services/conversion_service.py` — switched passthrough fragment iterator to `generate_frames` (pydicom 3 API)
- `ui/main_window.py` — "Force Re-encode" checkbox for MPEG-encapsulated files; passthrough files highlighted in cyan in table; spatial-stack files flagged with ⚠ warning in status column
- `main.py` — calls `configure_handlers()` at startup

---

## Phase 1 MVP

### Added
- Project scaffold: `pyproject.toml`, `requirements.txt`, full `src/` tree
- `utils/exceptions.py` — custom exception hierarchy
- `utils/logging_setup.py` — rotating file + console handler
- `utils/ffmpeg_utils.py` — FFmpeg binary discovery, version probe, codec presets
- `core/dicom_reader.py` — DICOM validation, transfer syntax detection, spatial-stack detection
- `core/fps_resolver.py` — 5-step FPS resolution chain with fallback and warnings
- `core/pixel_pipeline.py` — modality LUT, VOI LUT, MONOCHROME1 inversion, color conversion, 16→8 scaling
- `core/frame_extractor.py` — streaming frame iterator (uncompressed + encapsulated)
- `core/video_writer.py` — FFmpeg stdin pipe writer and MPEG stream-copy writer
- `services/conversion_service.py` — full read→extract→process→write orchestration
- `ui/main_window.py` — PyQt6 main window with drag-drop, file table, settings panel
- `ui/worker.py` — QThread worker with progress/log/cancel signals
- `ui/widgets.py` — DropZone, LogPanel, DualProgressBar
- `ui/metadata_dialog.py` — DICOM tag viewer with PHI highlighting
- `tests/` — unit tests for FPS resolver, pixel pipeline, DICOM reader, FFmpeg utils
- `docs/ARCHITECTURE.md`, `docs/DICOM_NOTES.md`
- `README.md` with install, run, troubleshooting

### Phase 2 (planned)
- All transfer syntaxes (RLE, JPEG-LS, JPEG 2000)
- Lossless FFV1 preset
- Encapsulated MPEG passthrough in UI

### Phase 3 (planned)
- Batch queue with per-file isolation
- Anonymization (PHI tag removal)
- JSON/CSV processing report
- Cancellation mid-frame
