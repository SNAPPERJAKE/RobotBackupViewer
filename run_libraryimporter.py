"""Dev launcher: python run_libraryimporter.py [--debug]"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from libraryimporter.app import main

if __name__ == "__main__":
    sys.exit(main())
