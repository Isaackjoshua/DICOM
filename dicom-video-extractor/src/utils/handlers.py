"""
Configure pydicom pixel-data handler priority at startup.

Priority order: pylibjpeg (covers JPEG / JPEG-LS / JPEG 2000 / RLE) before
gdcm so we use the lighter, pip-installable decoder first.
"""

import logging

import pydicom
import pydicom.config

logger = logging.getLogger(__name__)


def configure_handlers() -> None:
    """Set pylibjpeg ahead of gdcm in the handler list."""
    from pydicom.pixel_data_handlers import (
        gdcm_handler,
        numpy_handler,
        pylibjpeg_handler,
        rle_handler,
    )

    pydicom.config.pixel_data_handlers = [
        pylibjpeg_handler,  # JPEG / JPEG-LS / JPEG 2000 / RLE via pylibjpeg
        rle_handler,        # pydicom's own RLE path as backup
        numpy_handler,      # uncompressed
        gdcm_handler,       # last resort for edge-case syntaxes
    ]
    logger.info("pydicom handler priority configured: pylibjpeg → rle → numpy → gdcm")
