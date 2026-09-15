"""Fixed roles only. Standard output is exclusively a binary control channel."""

import msvcrt
import multiprocessing
import os
import sys


def main() -> int:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if stream is None:
            return 2
        msvcrt.setmode(stream.fileno(), os.O_BINARY)
    try:
        if sys.argv[1:] == ["--role=supervisor"]:
            from app.runtime.supervisor import run_supervisor

            return run_supervisor()
        if sys.argv[1:] == ["--role=api"]:
            from app.runtime.api_server import run_api

            return run_api()
        os.write(sys.stderr.fileno(), b"REQUEST_INVALID\n")
        return 2
    except TimeoutError:
        os.write(sys.stderr.fileno(), b"INIT_TIMEOUT\n")
        return 1
    except Exception:
        os.write(sys.stderr.fileno(), b"INTERNAL_ERROR\n")
        return 1


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
