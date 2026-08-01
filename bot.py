"""Entry point for the yt-audio-bot.

The implementation lives in the `ytbot` package (see ytbot/__init__.py for the
module map). This shim exists so the container command and the README's
`python bot.py` keep working unchanged.
"""

from ytbot.app import main

if __name__ == "__main__":
    main()
