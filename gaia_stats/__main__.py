"""python -m gaia_stats ingest INPUT... --output data/analysis.json
python -m gaia_stats serve --dataset data/analysis.json
"""
import argparse
import csv
import io
import json
import os
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .analysis import normalize, select, summarize, skill_context


def atomic_json(path, payload):
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=destination.parent, delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, indent=2)
            handle.write("\n")
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def ingest(paths, output):
    rows, rejected, seen = [], [], set()
    for path in paths:
        try:
            text = Path(path).read_text()
            try:
                parsed = json.loads(text)
                games = parsed if isinstance(parsed, list) else [parsed]
            except json.JSONDecodeError:
                games = [json.loads(line) for line in text.splitlines() if line.strip()]
        except (OSError, ValueError) as exc:
            rejected.append({"file": str(path), "reason": str(exc)})
            continue
        for game in games:
            identifier = game.get("slug") or game.get("_id") if isinstance(game, dict) else None
            try:
                if not identifier:
                    raise ValueError("Missing game identifier")
                if identifier in seen:
                    continue
                normalized = normalize(game)
                if any(not row["score_verified"] for row in normalized):
                    raise ValueError("VP ledger does not reconcile with final scores")
                rows.extend(normalized)
                seen.add(identifier)
            except (ValueError, KeyError, TypeError, IndexError, AttributeError) as exc:
                rejected.append({"file": str(path), "game_id": identifier, "reason": str(exc)})
    payload = {"schema_version": 1, "rows": rows, "rejected": rejected}
    if not rows:
        raise ValueError("No valid player records; existing dataset was not replaced")
    atomic_json(output, payload)
    print(f"Wrote {len(rows)} player records from {len(seen)} games; {len(rejected)} rejected")


def encode_csv(rows):
    output = io.StringIO()
    fields = list(rows[0]) if rows else ["game_id", "ruleset", "faction", "build_order", "score"]
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for row in rows:
        encoded = {k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v
                   for k, v in row.items()}
        # Spreadsheet formula injection guard for text in downloaded CSVs.
        writer.writerow({k: "'" + v if isinstance(v, str) and v.startswith(("=", "+", "-", "@")) else v
                         for k, v in encoded.items()})
    return output.getvalue().encode()

def response_for(dataset, path, filters):
    if path == "/":
        body = (Path(__file__).parent.parent / "web/index.html").read_bytes()
        content_type = "text/html; charset=utf-8"
    elif path in ("/api/analysis", "/api/export"):
        rows = select(dataset["rows"], filters)
        if path == "/api/export":
            body, content_type = encode_csv(rows), "text/csv; charset=utf-8"
        else:
            # Choices are scoped to the active ruleset, independent of narrower filters.
            cohort = select(dataset["rows"], {"ruleset": filters["ruleset"]})
            options = {key: sorted({row[key] for row in cohort}, key=str) for key in (
                "faction", "player_count", "layout", "auction", "faction_variant",
                "faction_variant_version", "official_center_sectors")}
            options["opponent"] = sorted({f for row in cohort for f in row["opponents"]})
            options["final_scoring"] = sorted({t for row in cohort for t in row["final_scorings"]})
            options["technology"] = sorted({t for row in cohort for t in row["technologies"].values()})
            for i in range(6):
                options[f"round{i+1}"] = sorted({r["round_scorings"][i] for r in cohort})
            body = json.dumps({"ruleset": filters["ruleset"], "options": options,
                               "skill": skill_context(dataset["rows"], filters),
                               "games": len({r["game_id"] for r in rows}),
                               "player_records": len(rows), "groups": summarize(rows),
                               "rows": rows, "rejected_games": len(dataset["rejected"])}).encode()
            content_type = "application/json"
    else:
        raise FileNotFoundError(path)
    return body, content_type


def handler_for(dataset):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            url = urlsplit(self.path)
            filters = {k: v[-1] for k, v in parse_qs(url.query).items()}
            try:
                body, content_type = response_for(dataset, url.path, filters)
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Cache-Control", "no-store")
                if url.path == "/api/export":
                    self.send_header("Content-Disposition", f'attachment; filename="gaia-{filters["ruleset"]}.csv"')
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except FileNotFoundError:
                self.send_error(404)
            except (ValueError, KeyError) as exc:
                self.send_error(400, str(exc))
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    loader = commands.add_parser("ingest")
    loader.add_argument("inputs", nargs="+")
    loader.add_argument("--output", default="data/analysis.json")
    fetcher = commands.add_parser("fetch", help="Download explicit finished BGS game slugs")
    fetcher.add_argument("slugs", nargs="+")
    fetcher.add_argument("--directory", default="data/raw")
    server = commands.add_parser("serve")
    server.add_argument("--dataset", default="data/analysis.json")
    server.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if args.command == "ingest":
        ingest(args.inputs, args.output)
    elif args.command == "fetch":
        from .fetch import fetch_games
        if fetch_games(args.slugs, args.directory):
            raise SystemExit(1)
    else:
        data = json.loads(Path(args.dataset).read_text())
        print(f"Gaia Stats: http://127.0.0.1:{args.port}", flush=True)
        ThreadingHTTPServer(("127.0.0.1", args.port), handler_for(data)).serve_forever()


if __name__ == "__main__":
    main()
