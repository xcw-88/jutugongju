"""Windows entry point: set physical-coordinate DPI awareness before Qt/MSS."""
import sys
from evidence_capture.native import enable_dpi_awareness

enable_dpi_awareness()

from evidence_capture.ui import main

if __name__ == "__main__":
    sys.exit(main())
