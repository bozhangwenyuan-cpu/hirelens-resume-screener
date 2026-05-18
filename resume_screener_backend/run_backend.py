from __future__ import annotations

import os
import sys
import traceback


ROOT = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(ROOT, "backend_startup.log")


def main() -> None:
    sys.path.insert(0, ROOT)
    os.chdir(os.path.dirname(ROOT))
    with open(LOG_PATH, "a", encoding="utf-8") as log:
        log.write("\n--- backend start ---\n")
        log.flush()
        try:
            import app

            app.run()
        except Exception:
            traceback.print_exc(file=log)
            log.flush()
            raise


if __name__ == "__main__":
    main()
