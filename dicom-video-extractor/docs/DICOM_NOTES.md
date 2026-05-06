# DICOM Real-World Notes

## 1. Transfer Syntax Decoder Map

Every DICOM file declares how its pixel data is encoded via `TransferSyntaxUID` in the file meta header (not the dataset). Reading it from the dataset is unreliable. For uncompressed data (`1.2.840.10008.1.2`, `.1.2.1`, `.1.2.2`) pydicom handles decoding natively. For everything else a separate decoder is needed:

- **RLE Lossless** — `pylibjpeg-rle`
- **JPEG / JPEG-LS** — `pylibjpeg-libjpeg`
- **JPEG 2000** — `pylibjpeg-openjpeg`
- **MPEG / H.264 / HEVC** — stream-copy passthrough (see §4)
- **Edge-case syntaxes** — `python-gdcm` as last resort

Always set `pydicom.config.pixel_data_handlers` to prefer pylibjpeg over gdcm.

## 2. MONOCHROME1 Polarity

In MONOCHROME1 images (common in X-ray), the minimum stored pixel value represents **white** and the maximum represents **black** — the opposite of display convention. Forgetting to invert after decoding produces a photo-negative video. The fix is simply: `frame = frame.max() - frame`. This must be applied *after* the modality LUT and VOI LUT, not before.

## 3. 16-bit Cine Loops

Echocardiography and angiography files are often stored as 12-bit data inside 16-bit containers. After the rescale slope/intercept step, the data must be mapped to 8-bit for H.264 encoding:

- If `WindowCenter` / `WindowWidth` are present, apply them — this is the calibrated view the radiologist sees.
- Otherwise, compute the 1st and 99th percentiles from the **first frame only**, then use those same scalars for every frame in the file. Computing new percentiles per frame causes flickering.

## 4. Encapsulated MPEG Passthrough

If the transfer syntax is MPEG-2, MPEG-4/H.264, or HEVC/H.265, the `PixelData` element already contains a valid compressed video elementary stream. Concatenate the encapsulation fragments (skipping the basic offset table at index 0) and pipe to `ffmpeg -i pipe:0 -c copy output.mp4`. This is dramatically faster than decoding frames and re-encoding, and produces bit-identical output.

Only fall back to frame-by-frame re-encoding if the user explicitly requests it (e.g. to change FPS or apply windowing to embedded data).

## 5. Multi-frame ≠ Cine

Not every multi-frame DICOM is a time series. CT and MR volumes are also stored as multi-frame DICOMs, with `FrameIncrementPointer` pointing to `SliceLocation` or similar spatial tags rather than `FrameTime`. Converting a CT volume to video produces a scrolling slice animation — not clinically wrong but also not what's usually expected. The application detects this case and warns the user before proceeding.

## 6. Pixel Aspect Ratio

Some DICOM files (particularly ultrasound) have non-square pixels — `PixelSpacing` rows ≠ cols. If this is ignored, the output video will be geometrically distorted. The correct approach is either:

- Resize the frame before encoding to produce square pixels, or
- Pass the correct aspect ratio to FFmpeg with `-aspect W:H`.

This application resizes the frame (baking the aspect ratio into the pixel dimensions) so the output is self-describing and works in all players.
