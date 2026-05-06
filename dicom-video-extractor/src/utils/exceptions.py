"""Custom exceptions for the DICOM video extractor."""


class DicomValidationError(Exception):
    """Raised when a file fails DICOM validation."""


class UnsupportedTransferSyntaxError(Exception):
    """Raised when a transfer syntax has no registered decoder."""

    def __init__(self, uid: str, name: str = ""):
        self.uid = uid
        self.name = name
        super().__init__(f"Unsupported transfer syntax: {name} ({uid})" if name else f"Unsupported transfer syntax: {uid}")


class MissingPixelDataError(Exception):
    """Raised when a DICOM dataset has no PixelData element."""


class FFmpegNotFoundError(Exception):
    """Raised when the FFmpeg binary cannot be located at startup."""


class FFmpegEncodingError(Exception):
    """Raised when FFmpeg exits non-zero during encoding."""

    def __init__(self, returncode: int, stderr_tail: str = ""):
        self.returncode = returncode
        self.stderr_tail = stderr_tail
        super().__init__(f"FFmpeg exited with code {returncode}.\n{stderr_tail}".strip())


class OutOfMemoryError(Exception):
    """Raised when pixel data is too large to materialise safely."""
