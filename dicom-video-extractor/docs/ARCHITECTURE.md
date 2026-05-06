# Architecture

## Pipeline Overview

```
DICOM file on disk
      │
      ▼
┌─────────────────┐
│  dicom_reader   │  validate, detect transfer syntax, count frames
└────────┬────────┘
         │ DicomFileInfo
         ▼
┌─────────────────┐
│  fps_resolver   │  CineRate → FrameTime → fallback → user override
└────────┬────────┘
         │ FpsResult
         ▼
┌─────────────────┐
│ frame_extractor │  lazy iterator — yields one decoded ndarray at a time
└────────┬────────┘
         │ np.ndarray (raw, decoded)
         ▼
┌─────────────────┐
│ pixel_pipeline  │  modality LUT → VOI LUT → MONOCHROME1 invert
│                 │  → color convert → 16→8 bit scaling
└────────┬────────┘
         │ np.ndarray (uint8, C-contiguous)
         ▼
┌─────────────────┐
│  video_writer   │  FFmpeg stdin pipe  (or stream-copy for MPEG encapsulated)
└────────┬────────┘
         │
         ▼
   MP4 / AVI / MKV
```

## Threading Model

All DICOM I/O and pixel processing runs on a dedicated `QThread` via `ConversionWorker`.  
The GUI thread only handles signals emitted by the worker:

```
GUI Thread                          Worker Thread
───────────                         ─────────────
QMainWindow._start_conversion()
  → ConversionWorker.run()          ← started via QThread.started signal
                                    → conversion_service.convert()
                                        → frame_extractor.iter_frames()
                                        → pixel_pipeline.process_frame()
                                        → video_writer.VideoWriter.write_frame()
  worker.progress(cur, tot) ──────► DualProgressBar.update_file_progress()
  worker.log(msg, level)   ──────► LogPanel.append_log()
  worker.file_done(path, ok) ────► MainWindow._on_file_done()
  worker.finished()        ──────► MainWindow._on_finished()
```

**Rule:** No Qt widget calls from the worker thread. No DICOM I/O from the GUI thread.

## Cancellation

A `threading.Event` (`cancel_event`) is shared between the GUI and the worker.  
The worker checks it between frames and after each FFmpeg flush. On cancellation,
`VideoWriter.__exit__` deletes the partial output file.

## Memory Strategy

For files where `N × H × W × bytes_per_pixel > 1 GB`, the frame extractor slices
the raw `PixelData` bytes directly (uncompressed) or iterates `generate_pixel_data_frame`
(encapsulated) — never materialising the full array. Volume-level scalars are computed
from the first frame only and reused for all subsequent frames.
