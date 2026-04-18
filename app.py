from __future__ import annotations

import json
import os
import queue
import re
import threading
import time
import uuid
from copy import deepcopy
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib import error, request
from urllib.parse import parse_qs, urlparse


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = BASE_DIR / "data"
STATE_FILE = DATA_DIR / "game_state.json"
SUPABASE_TABLE = os.environ.get("SUPABASE_TABLE", "game_state")

MAX_PLAYERS = 20
MAX_FLIGHT_SIZE = 4

COURSE = {
    "name": "Islamabad Club",
    "holes": [
        {"number": 1, "par": 4, "index": 17},
        {"number": 2, "par": 4, "index": 5},
        {"number": 3, "par": 3, "index": 13},
        {"number": 4, "par": 4, "index": 1},
        {"number": 5, "par": 3, "index": 7},
        {"number": 6, "par": 5, "index": 11},
        {"number": 7, "par": 4, "index": 3},
        {"number": 8, "par": 4, "index": 9},
        {"number": 9, "par": 5, "index": 15},
        {"number": 10, "par": 4, "index": 2},
        {"number": 11, "par": 4, "index": 4},
        {"number": 12, "par": 3, "index": 14},
        {"number": 13, "par": 4, "index": 6},
        {"number": 14, "par": 3, "index": 18},
        {"number": 15, "par": 4, "index": 12},
        {"number": 16, "par": 4, "index": 16},
        {"number": 17, "par": 5, "index": 10},
        {"number": 18, "par": 5, "index": 8},
    ],
}


def default_state() -> dict[str, Any]:
    return {
        "id": "",
        "name": "Untitled Tournament",
        "status": "active",
        "course": COURSE,
        "players": [],
        "scores": {},
        "updated_at": time.time(),
    }


class StorageBackend:
    def load_tournament(self, tournament_id: str) -> dict[str, Any] | None:
        raise NotImplementedError

    def save_tournament(self, tournament_id: str, state: dict[str, Any]) -> None:
        raise NotImplementedError

    def create_tournament(self, tournament_id: str, state: dict[str, Any]) -> dict[str, Any]:
        self.save_tournament(tournament_id, state)
        return state

    def list_tournaments(self) -> list[dict[str, Any]]:
        raise NotImplementedError


class FileStorage(StorageBackend):
    def __init__(self, path: Path) -> None:
        self.path = path

    def _load_all(self) -> dict[str, dict[str, Any]]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._save_all({})
            return {}
        with self.path.open("r", encoding="utf-8") as fh:
            loaded = json.load(fh)
        if self._looks_like_legacy_state(loaded):
            legacy = self._normalize_state(loaded, loaded.get("id") or "legacy")
            return {legacy["id"]: legacy}
        return {
            tournament_id: self._normalize_state(state, tournament_id)
            for tournament_id, state in loaded.items()
        }

    def _save_all(self, tournaments: dict[str, dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as fh:
            json.dump(tournaments, fh, indent=2)

    def load_tournament(self, tournament_id: str) -> dict[str, Any] | None:
        tournaments = self._load_all()
        state = tournaments.get(tournament_id)
        return deepcopy(state) if state else None

    def save_tournament(self, tournament_id: str, state: dict[str, Any]) -> None:
        tournaments = self._load_all()
        tournaments[tournament_id] = self._normalize_state(state, tournament_id)
        self._save_all(tournaments)

    def list_tournaments(self) -> list[dict[str, Any]]:
        tournaments = self._load_all()
        return [
            {
                "id": state["id"],
                "name": state.get("name", "Untitled Tournament"),
                "status": state.get("status", "active"),
                "updated_at": state.get("updated_at"),
                "player_count": len(state.get("players", [])),
            }
            for state in tournaments.values()
        ]

    def _normalize_state(self, state: dict[str, Any], tournament_id: str) -> dict[str, Any]:
        normalized = deepcopy(state)
        normalized["id"] = tournament_id
        normalized.setdefault("name", "Untitled Tournament")
        normalized.setdefault("status", "active")
        normalized.setdefault("course", COURSE)
        normalized.setdefault("players", [])
        normalized.setdefault("scores", {})
        normalized.setdefault("updated_at", time.time())
        return normalized

    def _looks_like_legacy_state(self, payload: dict[str, Any]) -> bool:
        return "course" in payload and "players" in payload and "scores" in payload


class SupabaseStorage(StorageBackend):
    def __init__(self, url: str, service_role_key: str, table: str) -> None:
        self.url = url.rstrip("/")
        self.service_role_key = service_role_key
        self.table = table
        self.base_endpoint = f"{self.url}/rest/v1/{self.table}"

    def load_tournament(self, tournament_id: str) -> dict[str, Any] | None:
        query_url = f"{self.base_endpoint}?select=state&id=eq.{tournament_id}&limit=1"
        payload = self._request("GET", query_url)
        if payload:
            return self._normalize_state(payload[0].get("state") or default_state(), tournament_id)
        return None

    def save_tournament(self, tournament_id: str, state: dict[str, Any]) -> None:
        body = {
            "id": tournament_id,
            "state": self._normalize_state(state, tournament_id),
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        self._request(
            "POST",
            self.base_endpoint,
            body=body,
            extra_headers={"Prefer": "resolution=merge-duplicates"},
        )

    def list_tournaments(self) -> list[dict[str, Any]]:
        query_url = f"{self.base_endpoint}?select=id,state,updated_at&order=updated_at.desc"
        payload = self._request("GET", query_url)
        tournaments = []
        for row in payload or []:
            state = self._normalize_state(row.get("state") or default_state(), row["id"])
            tournaments.append(
                {
                    "id": state["id"],
                    "name": state.get("name", "Untitled Tournament"),
                    "status": state.get("status", "active"),
                    "updated_at": state.get("updated_at"),
                    "player_count": len(state.get("players", [])),
                }
            )
        return tournaments

    def _request(
        self,
        method: str,
        url: str,
        body: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> Any:
        data = None
        headers = {
            "apikey": self.service_role_key,
            "Authorization": f"Bearer {self.service_role_key}",
            "Content-Type": "application/json",
        }
        if extra_headers:
            headers.update(extra_headers)
        if body is not None:
            data = json.dumps(body).encode("utf-8")
        req = request.Request(url, data=data, headers=headers, method=method)
        try:
            with request.urlopen(req, timeout=10) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Supabase request failed with {exc.code}: {details}"
            ) from exc
        except error.URLError as exc:
            raise RuntimeError(f"Could not connect to Supabase: {exc.reason}") from exc

    def _normalize_state(self, state: dict[str, Any], tournament_id: str) -> dict[str, Any]:
        normalized = deepcopy(state)
        normalized["id"] = tournament_id
        normalized.setdefault("name", "Untitled Tournament")
        normalized.setdefault("status", "active")
        normalized.setdefault("course", COURSE)
        normalized.setdefault("players", [])
        normalized.setdefault("scores", {})
        normalized.setdefault("updated_at", time.time())
        return normalized


def create_storage() -> StorageBackend:
    supabase_url = os.environ.get("SUPABASE_URL", "").strip()
    supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if supabase_url and supabase_key:
        return SupabaseStorage(supabase_url, supabase_key, SUPABASE_TABLE)
    return FileStorage(STATE_FILE)


def make_tournament_id() -> str:
    return uuid.uuid4().hex[:10]


class TournamentStore:
    def __init__(self, storage: StorageBackend) -> None:
        self.storage = storage
        self.lock = threading.Lock()
        self.subscribers: dict[str, list[queue.Queue[str]]] = {}

    def create_tournament(self, name: str) -> dict[str, Any]:
        tournament_id = make_tournament_id()
        state = default_state()
        state["id"] = tournament_id
        state["name"] = name or "Untitled Tournament"
        with self.lock:
            created = self.storage.create_tournament(tournament_id, state)
        return build_response(created)

    def list_tournaments(self) -> list[dict[str, Any]]:
        with self.lock:
            return self.storage.list_tournaments()

    def get_state(self, tournament_id: str) -> dict[str, Any]:
        with self.lock:
            state = self.storage.load_tournament(tournament_id)
        if not state:
            raise ValueError("Tournament not found.")
        return deepcopy(state)

    def replace_players(self, tournament_id: str, players: list[dict[str, Any]]) -> dict[str, Any]:
        validated = self._validate_players(players)
        with self.lock:
            state = self.storage.load_tournament(tournament_id)
            if not state:
                raise ValueError("Tournament not found.")
            state["players"] = validated
            state["scores"] = {player["id"]: {} for player in validated}
            state["updated_at"] = time.time()
            self.storage.save_tournament(tournament_id, state)
            snapshot = deepcopy(state)
        self._broadcast(tournament_id, snapshot)
        return snapshot

    def update_hole_scores(
        self, tournament_id: str, flight_id: str, hole: int, score_entries: list[dict[str, Any]]
    ) -> dict[str, Any]:
        hole_key = str(hole)
        hole_data = get_hole(hole)
        if not hole_data:
            raise ValueError("Invalid hole number.")
        if not isinstance(score_entries, list) or not score_entries:
            raise ValueError("At least one score entry is required.")

        with self.lock:
            state = self.storage.load_tournament(tournament_id)
            if not state:
                raise ValueError("Tournament not found.")
            flight_players = {player["id"]: player for player in state["players"] if player["flight_id"] == flight_id}
            if not flight_players:
                raise ValueError("Flight not found.")

            for entry in score_entries:
                player_id = entry.get("player_id", "")
                gross = entry.get("gross")
                if player_id not in flight_players:
                    raise ValueError("Score entry includes a player outside this flight.")
                if gross in (None, ""):
                    state["scores"].setdefault(player_id, {}).pop(hole_key, None)
                    continue
                if not isinstance(gross, int):
                    raise ValueError("Gross score must be an integer.")
                if gross < 1 or gross > 20:
                    raise ValueError("Gross score must be between 1 and 20.")
                state["scores"].setdefault(player_id, {})[hole_key] = gross

            state["updated_at"] = time.time()
            self.storage.save_tournament(tournament_id, state)
            snapshot = deepcopy(state)

        self._broadcast(tournament_id, snapshot)
        return snapshot

    def update_flight_scores(
        self, tournament_id: str, flight_id: str, scorecard: dict[str, list[dict[str, Any]]]
    ) -> dict[str, Any]:
        if not isinstance(scorecard, dict) or not scorecard:
            raise ValueError("Scorecard payload is required.")

        with self.lock:
            state = self.storage.load_tournament(tournament_id)
            if not state:
                raise ValueError("Tournament not found.")
            flight_players = {player["id"]: player for player in state["players"] if player["flight_id"] == flight_id}
            if not flight_players:
                raise ValueError("Flight not found.")

            for hole_key, entries in scorecard.items():
                try:
                    hole = int(hole_key)
                except ValueError as exc:
                    raise ValueError("Invalid hole number.") from exc
                if not get_hole(hole):
                    raise ValueError("Invalid hole number.")
                if not isinstance(entries, list):
                    raise ValueError("Each hole must include a list of scores.")

                for entry in entries:
                    player_id = entry.get("player_id", "")
                    gross = entry.get("gross")
                    if player_id not in flight_players:
                        raise ValueError("Score entry includes a player outside this flight.")
                    if gross in (None, ""):
                        state["scores"].setdefault(player_id, {}).pop(hole_key, None)
                        continue
                    if not isinstance(gross, int):
                        raise ValueError("Gross score must be an integer.")
                    if gross < 1 or gross > 20:
                        raise ValueError("Gross score must be between 1 and 20.")
                    state["scores"].setdefault(player_id, {})[hole_key] = gross

            state["updated_at"] = time.time()
            self.storage.save_tournament(tournament_id, state)
            snapshot = deepcopy(state)

        self._broadcast(tournament_id, snapshot)
        return snapshot

    def register(self, tournament_id: str) -> queue.Queue[str]:
        subscription: queue.Queue[str] = queue.Queue()
        with self.lock:
            self.subscribers.setdefault(tournament_id, []).append(subscription)
        return subscription

    def unregister(self, tournament_id: str, subscription: queue.Queue[str]) -> None:
        with self.lock:
            bucket = self.subscribers.get(tournament_id, [])
            if subscription in bucket:
                bucket.remove(subscription)

    def _broadcast(self, tournament_id: str, state: dict[str, Any]) -> None:
        payload = json.dumps(build_response(state))
        dead: list[queue.Queue[str]] = []
        with self.lock:
            subscribers = list(self.subscribers.get(tournament_id, []))
        for subscriber in subscribers:
            try:
                subscriber.put_nowait(payload)
            except Exception:
                dead.append(subscriber)
        if dead:
            with self.lock:
                self.subscribers[tournament_id] = [
                    sub for sub in self.subscribers.get(tournament_id, []) if sub not in dead
                ]

    def _validate_players(self, players: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not isinstance(players, list):
            raise ValueError("Players payload must be a list.")
        if not players:
            raise ValueError("Add at least one player.")
        if len(players) > MAX_PLAYERS:
            raise ValueError(f"Maximum {MAX_PLAYERS} players are supported.")

        normalized: list[dict[str, Any]] = []
        flight_counts: dict[str, int] = {}
        for index, player in enumerate(players, start=1):
            name = str(player.get("name", "")).strip()
            if not name:
                raise ValueError(f"Player {index} is missing a name.")
            handicap = player.get("handicap")
            if not isinstance(handicap, int) or handicap < 0 or handicap > 54:
                raise ValueError(f"{name} must have a handicap between 0 and 54.")
            flight_id = str(player.get("flight_id", "")).strip()
            if not flight_id:
                raise ValueError(f"{name} must be assigned to a flight.")
            flight_counts[flight_id] = flight_counts.get(flight_id, 0) + 1
            if flight_counts[flight_id] > MAX_FLIGHT_SIZE:
                raise ValueError(
                    f"Flight {flight_id} exceeds the maximum of {MAX_FLIGHT_SIZE} players."
                )
            normalized.append(
                {
                    "id": player.get("id") or uuid.uuid4().hex[:8],
                    "name": name,
                    "handicap": handicap,
                    "flight_id": flight_id,
                }
            )
        return normalized


def get_hole(hole_number: int) -> dict[str, Any] | None:
    return next((hole for hole in COURSE["holes"] if hole["number"] == hole_number), None)


def shots_received(handicap: int, stroke_index: int) -> int:
    full_rounds = handicap // 18
    remainder = handicap % 18
    return full_rounds + (1 if remainder and stroke_index <= remainder else 0)


def stableford_points(par: int, net_score: int) -> int:
    return max(0, 2 + (par - net_score))


def build_response(state: dict[str, Any]) -> dict[str, Any]:
    players = deepcopy(state["players"])
    scores = deepcopy(state["scores"])
    flights: dict[str, dict[str, Any]] = {}
    leaderboard: list[dict[str, Any]] = []

    for player in players:
        player_scores = scores.get(player["id"], {})
        hole_rows = []
        gross_total = 0
        net_total = 0
        stableford_total = 0
        holes_played = 0

        for hole in COURSE["holes"]:
            gross = player_scores.get(str(hole["number"]))
            allowance = shots_received(player["handicap"], hole["index"])
            net = None
            points = None
            if gross is not None:
                net = gross - allowance
                points = stableford_points(hole["par"], net)
                gross_total += gross
                net_total += net
                stableford_total += points
                holes_played += 1
            hole_rows.append(
                {
                    "hole": hole["number"],
                    "par": hole["par"],
                    "index": hole["index"],
                    "gross": gross,
                    "shots_received": allowance,
                    "net": net,
                    "stableford": points,
                }
            )

        leaderboard_row = {
            "player_id": player["id"],
            "name": player["name"],
            "flight_id": player["flight_id"],
            "handicap": player["handicap"],
            "gross_total": gross_total,
            "net_total": net_total,
            "stableford_total": stableford_total,
            "holes_played": holes_played,
            "hole_scores": hole_rows,
        }
        leaderboard.append(leaderboard_row)

        flight = flights.setdefault(
            player["flight_id"],
            {"flight_id": player["flight_id"], "players": []},
        )
        flight["players"].append(leaderboard_row)

    leaderboard.sort(
        key=lambda row: (
            -row["stableford_total"],
            row["net_total"] if row["holes_played"] else 9999,
            row["gross_total"] if row["holes_played"] else 9999,
            row["name"].lower(),
        )
    )

    ordered_flights = sorted(
        flights.values(),
        key=lambda flight: flight["flight_id"].lower(),
    )

    return {
        "id": state["id"],
        "name": state.get("name", "Untitled Tournament"),
        "status": state.get("status", "active"),
        "course": COURSE,
        "players": players,
        "flights": ordered_flights,
        "leaderboard": leaderboard,
        "updated_at": state.get("updated_at"),
    }


STORE = TournamentStore(create_storage())


class GolfHandler(BaseHTTPRequestHandler):
    server_version = "GolfScoring/1.0"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)

        if parsed.path == "/":
            self._serve_file(STATIC_DIR / "home.html", "text/html; charset=utf-8")
            return
        tournament_match = re.fullmatch(r"/t/([a-z0-9]+)", parsed.path)
        if tournament_match:
            self._serve_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
            return
        if parsed.path == "/styles.css":
            self._serve_file(STATIC_DIR / "styles.css", "text/css; charset=utf-8")
            return
        if parsed.path == "/app.js":
            self._serve_file(STATIC_DIR / "app.js", "application/javascript; charset=utf-8")
            return
        if parsed.path == "/home.js":
            self._serve_file(STATIC_DIR / "home.js", "application/javascript; charset=utf-8")
            return
        tournament_state_match = re.fullmatch(r"/api/tournaments/([a-z0-9]+)/state", parsed.path)
        if tournament_state_match:
            try:
                state = STORE.get_state(tournament_state_match.group(1))
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
                return
            self._send_json(build_response(state))
            return
        tournament_events_match = re.fullmatch(r"/api/tournaments/([a-z0-9]+)/events", parsed.path)
        if tournament_events_match:
            self._serve_events(tournament_events_match.group(1))
            return
        if parsed.path == "/api/tournaments":
            tournaments = STORE.list_tournaments()
            self._send_json({"tournaments": tournaments})
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)

        if parsed.path == "/api/tournaments":
            payload = self._read_json()
            created = STORE.create_tournament(str(payload.get("name", "")).strip())
            created["share_url"] = self._tournament_url(created["id"])
            self._send_json(created, status=HTTPStatus.CREATED)
            return
        tournament_setup_match = re.fullmatch(r"/api/tournaments/([a-z0-9]+)/setup", parsed.path)
        if tournament_setup_match:
            payload = self._read_json()
            try:
                state = STORE.replace_players(tournament_setup_match.group(1), payload.get("players", []))
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            response = build_response(state)
            response["share_url"] = self._tournament_url(response["id"])
            self._send_json(response)
            return

        tournament_score_match = re.fullmatch(r"/api/tournaments/([a-z0-9]+)/score", parsed.path)
        if tournament_score_match:
            payload = self._read_json()
            try:
                hole = int(payload.get("hole"))
                state = STORE.update_hole_scores(
                    tournament_score_match.group(1),
                    str(payload.get("flight_id", "")).strip(),
                    hole,
                    payload.get("scores", []),
                )
            except (ValueError, TypeError) as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json(build_response(state))
            return

        tournament_flight_scores_match = re.fullmatch(
            r"/api/tournaments/([a-z0-9]+)/flight-scores", parsed.path
        )
        if tournament_flight_scores_match:
            payload = self._read_json()
            try:
                state = STORE.update_flight_scores(
                    tournament_flight_scores_match.group(1),
                    str(payload.get("flight_id", "")).strip(),
                    payload.get("scorecard", {}),
                )
            except (ValueError, TypeError) as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json(build_response(state))
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        tournament_score_match = re.fullmatch(r"/api/tournaments/([a-z0-9]+)/score", parsed.path)
        if not tournament_score_match:
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
            return

        params = parse_qs(parsed.query)
        try:
            flight_id = params["flight_id"][0]
            hole = int(params["hole"][0])
        except (KeyError, IndexError, ValueError):
            self._send_json({"error": "flight_id and hole are required."}, status=400)
            return

        try:
            state = STORE.get_state(tournament_score_match.group(1))
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
            return
        flight_players = [
            player for player in state["players"] if player["flight_id"] == flight_id
        ]
        payload = {
            "flight_id": flight_id,
            "hole": hole,
            "scores": [{"player_id": player["id"], "gross": ""} for player in flight_players],
        }
        try:
            updated = STORE.update_hole_scores(
                tournament_score_match.group(1), flight_id, hole, payload["scores"]
            )
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        self._send_json(build_response(updated))

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _serve_file(self, path: Path, content_type: str) -> None:
        if not path.exists():
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
            return
        data = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _serve_events(self, tournament_id: str) -> None:
        try:
            current_state = STORE.get_state(tournament_id)
        except ValueError:
            self.send_error(HTTPStatus.NOT_FOUND, "Tournament not found")
            return
        subscription = STORE.register(tournament_id)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        try:
            initial_payload = json.dumps(build_response(current_state))
            self.wfile.write(f"data: {initial_payload}\n\n".encode("utf-8"))
            self.wfile.flush()

            while True:
                try:
                    payload = subscription.get(timeout=15)
                    self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                except queue.Empty:
                    self.wfile.write(b": keepalive\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            STORE.unregister(tournament_id, subscription)

    def _tournament_url(self, tournament_id: str) -> str:
        host = self.headers.get("Host", f"localhost:{os.environ.get('PORT', '8000')}")
        protocol = "https" if self.headers.get("X-Forwarded-Proto") == "https" else "http"
        return f"{protocol}://{host}/t/{tournament_id}"


def run() -> None:
    host = "0.0.0.0"
    port = int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer((host, port), GolfHandler)
    print(f"Golf scoring app running on port {port}")
    server.serve_forever()


if __name__ == "__main__":
    run()
