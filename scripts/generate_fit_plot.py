#!/usr/bin/env python3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from minions.app import PLOT_PATH, unit_fit_payload, write_unit_fit_svg


def main() -> None:
    write_unit_fit_svg(PLOT_PATH)
    payload = unit_fit_payload()
    print(f"wrote {Path(PLOT_PATH)}")
    print(f"alpha={payload['alpha']:.6f}")


if __name__ == "__main__":
    main()
