from __future__ import annotations

import argparse
import json
import mimetypes
import traceback
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from .ai.player import play_turn
from .rules.game import Game, RuleError, apply_action, create_game, join_game
from .rules.maps import generate_map
from .rules.spells import spell_catalog
from .rules.units import ALPHA, EXISTING_UNITS, all_auxiliary_units, generate_random_unit, predicted_expression


ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "web" / "static"
PLOT_PATH = STATIC / "unit-fit.svg"


class GameStore:
    def __init__(self) -> None:
        self.games: Dict[str, Game] = {}

    def create(self, boards: int) -> Game:
        game = create_game(boards)
        while game.code in self.games:
            game = create_game(boards)
        self.games[game.code] = game
        return game

    def get(self, code: str) -> Game:
        game = self.games.get(code.upper())
        if not game:
            raise RuleError("unknown game code")
        return game


STORE = GameStore()


def unit_fit_payload() -> dict:
    points = []
    for unit in EXISTING_UNITS:
        observed = unit.cost * unit.cost - unit.rebate * unit.rebate
        predicted = predicted_expression(unit)
        points.append(
            {
                "name": unit.name,
                "observed": observed,
                "predicted": predicted,
                "power": unit.to_dict()["power"],
            }
        )
    return {"alpha": ALPHA, "points": points}


def write_unit_fit_svg(path: Path = PLOT_PATH) -> None:
    payload = unit_fit_payload()
    points = payload["points"]
    if not points:
        return
    width = 980
    height = 680
    pad = 70
    max_value = max(max(point["observed"], point["predicted"]) for point in points) * 1.15

    def sx(value: float) -> float:
        return pad + (width - 2 * pad) * value / max_value

    def sy(value: float) -> float:
        return height - pad - (height - 2 * pad) * value / max_value

    lines = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="980" height="680" viewBox="0 0 980 680">',
        '<rect width="980" height="680" fill="#f8f3e7"/>',
        '<text x="490" y="36" text-anchor="middle" font-family="Inter,Arial" font-size="24" font-weight="700">Unit Cost Fit</text>',
        f'<text x="490" y="62" text-anchor="middle" font-family="Inter,Arial" font-size="14">alpha = {payload["alpha"]:.4f}; y = predicted (C^2 - R^2), x = printed value</text>',
        f'<line x1="{pad}" y1="{height-pad}" x2="{width-pad}" y2="{height-pad}" stroke="#2d2118" stroke-width="2"/>',
        f'<line x1="{pad}" y1="{height-pad}" x2="{pad}" y2="{pad}" stroke="#2d2118" stroke-width="2"/>',
        f'<line x1="{pad}" y1="{height-pad}" x2="{width-pad}" y2="{pad}" stroke="#8c5d2e" stroke-width="2" stroke-dasharray="8 6"/>',
        f'<text x="{width/2}" y="{height-20}" text-anchor="middle" font-family="Inter,Arial" font-size="14">Observed (Cost - Rebate)(Cost + Rebate)</text>',
        f'<text x="22" y="{height/2}" transform="rotate(-90 22 {height/2})" text-anchor="middle" font-family="Inter,Arial" font-size="14">Predicted alpha * Unit Power</text>',
    ]
    for tick in range(0, int(max_value) + 1, max(5, int(max_value // 6) or 5)):
        x = sx(tick)
        y = sy(tick)
        lines.append(f'<line x1="{x:.1f}" y1="{height-pad}" x2="{x:.1f}" y2="{height-pad+6}" stroke="#2d2118"/>')
        lines.append(f'<line x1="{pad-6}" y1="{y:.1f}" x2="{pad}" y2="{y:.1f}" stroke="#2d2118"/>')
        lines.append(f'<text x="{x:.1f}" y="{height-pad+24}" text-anchor="middle" font-family="Inter,Arial" font-size="11">{tick}</text>')
        lines.append(f'<text x="{pad-12}" y="{y+4:.1f}" text-anchor="end" font-family="Inter,Arial" font-size="11">{tick}</text>')
    for idx, point in enumerate(points):
        x = sx(point["observed"])
        y = sy(point["predicted"])
        dx = 8 if idx % 2 == 0 else -8
        anchor = "start" if dx > 0 else "end"
        lines.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="#ffd447" stroke="#271d14" stroke-width="1.5"/>')
        lines.append(
            f'<text x="{x+dx:.1f}" y="{y-8:.1f}" text-anchor="{anchor}" font-family="Inter,Arial" font-size="11" fill="#271d14">{point["name"]}</text>'
        )
    lines.append("</svg>")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version = "MinionsOfDarkness/0.1"

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"{self.address_string()} - {fmt % args}")

    def do_GET(self) -> None:
        try:
            self._handle_get()
        except Exception as exc:
            self._send_error(exc)

    def do_POST(self) -> None:
        try:
            self._handle_post()
        except Exception as exc:
            self._send_error(exc)

    def _handle_get(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/":
            self._send_file(STATIC / "index.html")
            return
        if path.startswith("/static/"):
            self._send_file(STATIC / path[len("/static/") :])
            return
        if path == "/api/generators/map":
            seed = _optional_int(parse_qs(parsed.query).get("seed", [None])[0])
            self._json({"map": generate_map(seed=seed).to_dict()})
            return
        if path == "/api/generators/unit":
            seed = _optional_int(parse_qs(parsed.query).get("seed", [None])[0])
            self._json({"unit": generate_random_unit(seed=seed).to_dict(), "alpha": ALPHA})
            return
        if path == "/api/units/fit":
            self._json(unit_fit_payload())
            return
        if path == "/api/units/auxiliary":
            self._json({"units": all_auxiliary_units()})
            return
        if path == "/api/spells":
            self._json({"spells": spell_catalog()})
            return
        parts = _parts(path)
        if len(parts) == 3 and parts[:2] == ["api", "games"]:
            self._json({"game": STORE.get(parts[2]).to_dict()})
            return
        raise RuleError("not found")

    def _handle_post(self) -> None:
        path = urlparse(self.path).path
        body = self._body()
        if path == "/api/games":
            game = STORE.create(int(body.get("boards", 1)))
            self._json({"game": game.to_dict()})
            return
        parts = _parts(path)
        if len(parts) == 4 and parts[:2] == ["api", "games"] and parts[3] == "join":
            game = STORE.get(parts[2])
            color = body.get("color", "")
            join_game(game, color, body.get("name", ""))
            self._json({"game": game.to_dict()})
            return
        if len(parts) == 4 and parts[:2] == ["api", "games"] and parts[3] == "actions":
            game = STORE.get(parts[2])
            color = body.get("color", "")
            action = body.get("action", "")
            payload = body.get("payload", {})
            try:
                result = apply_action(game, color, action, payload)
            except RuleError as exc:
                self._json({"error": str(exc), "game": game.to_dict()}, status=400)
                return
            self._json({"game": game.to_dict(), "result": result})
            return
        if len(parts) == 4 and parts[:2] == ["api", "games"] and parts[3] == "ai-turn":
            game = STORE.get(parts[2])
            color = body.get("color", game.turn)
            time_limit = max(0.1, min(60.0, float(body.get("timeLimit", 10.0))))
            try:
                result = play_turn(game, color, time_limit=time_limit)
            except RuleError as exc:
                self._json({"error": str(exc), "game": game.to_dict()}, status=400)
                return
            self._json({"game": game.to_dict(), "result": result.to_dict()})
            return
        raise RuleError("not found")

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if not length:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw)

    def _json(self, payload: dict, status: int = 200) -> None:
        data = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_file(self, path: Path) -> None:
        if not path.exists() or not path.is_file():
            raise RuleError("not found")
        content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        data = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_error(self, exc: Exception) -> None:
        status = 400 if isinstance(exc, RuleError) else 500
        if status == 500:
            traceback.print_exc()
        payload = {"error": str(exc)}
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def _parts(path: str) -> list:
    return [part for part in path.strip("/").split("/") if part]


def _optional_int(value: Optional[str]) -> Optional[int]:
    if value in (None, ""):
        return None
    return int(value)


def serve(host: str, port: int) -> None:
    write_unit_fit_svg()
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"Minions of Darkness listening on http://{host}:{port}")
    httpd.serve_forever()


def main(argv: Optional[list] = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    serve(args.host, args.port)


if __name__ == "__main__":
    main()
