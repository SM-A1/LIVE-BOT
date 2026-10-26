"""Root entrypoint for hosts that expect `main.py` (Botkeep). Run: python main.py"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.main import main  # noqa: E402

if __name__ == "__main__":
    asyncio.run(main())
