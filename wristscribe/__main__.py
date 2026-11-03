"""Command-line entry point: `python -m wristscribe [init|run|send|transcribe]`."""

from __future__ import annotations

import argparse
import getpass
import logging
import sys
import time
from pathlib import Path

from . import __version__
from .cleanup import CleanupError, TextCleaner
from .config import ConfigError, load_config, write_initial_config
from .dictation import DictationService
from .net import lan_ip
from .output import PrintOutput, make_output
from .server import WristScribeServer
from .transcriber import CloudTranscriber, TranscriptionError

COMMANDS = ("init", "run", "send", "transcribe", "clean")


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-c", "--config", default="config.toml", help="config file (default: config.toml)")
    common.add_argument("-v", "--verbose", action="store_true", help="show debug logs")

    parser = argparse.ArgumentParser(
        prog="wristscribe",
        description="Dictate on your Apple Watch; the text appears at your laptop's cursor.",
    )
    parser.add_argument("--version", action="version", version=f"WristScribe {__version__}")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("init", parents=[common], help="create config.toml with a fresh token")
    p.add_argument("--force", action="store_true", help="overwrite an existing config")

    p = sub.add_parser("run", parents=[common], help="start listening for the watch (default)")
    p.add_argument("--dry-run", action="store_true", help="print dictations instead of typing them")

    p = sub.add_parser("send", parents=[common], help="send test text to a running WristScribe")
    p.add_argument("text", nargs="+")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--delay", type=float, default=3.0, help="seconds to wait so you can click a text box")

    p = sub.add_parser("transcribe", parents=[common], help="transcribe an audio file (checks your API key)")
    p.add_argument("file", type=Path)

    p = sub.add_parser("clean", parents=[common], help="run the AI cleanup on some text (checks your API key)")
    p.add_argument("text", nargs="+")
    return parser


def cmd_init(args: argparse.Namespace) -> int:
    path = Path(args.config)
    if path.exists() and not args.force:
        print(f"{path} already exists. Use --force to replace it.")
        return 1
    api_key = ""
    if sys.stdin.isatty():
        print("Get a free Groq API key at https://console.groq.com/keys")
        api_key = getpass.getpass("Paste it here (hidden; press Enter to skip): ").strip()
    token = write_initial_config(path, api_key)
    print(f"\nCreated {path.resolve()}")
    print(f"Your token: {token}")
    print("Next: python -m wristscribe run")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    output = PrintOutput() if args.dry_run else make_output(cfg.output.mode, cfg.output.restore_clipboard)
    transcriber = CloudTranscriber.from_config(cfg.transcription)
    has_key = bool(transcriber.api_key)
    cleaner = TextCleaner.from_config(cfg.cleanup, cfg.transcription) if cfg.cleanup.enabled and has_key else None
    service = DictationService(transcriber, output, append_space=cfg.output.append_space, cleaner=cleaner)
    try:
        server = WristScribeServer((cfg.server.host, cfg.server.port), cfg.server.token, service)
    except OSError as exc:
        print(f"Could not listen on port {cfg.server.port}: {exc}")
        print("Is WristScribe already running? Otherwise change [server] port in the config.")
        return 1

    base = f"http://{lan_ip()}:{cfg.server.port}"
    token = cfg.server.token
    t = cfg.transcription
    if cleaner:
        cleanup = f"on ({t.provider} / {cleaner.model})"
    else:
        cleanup = "off" if not cfg.cleanup.enabled else "off (needs an API key)"
    print(f"""
WristScribe {__version__} is listening.

  Shortcut A URL (Dictate to PC) : {base}/text?token={token}
  Shortcut B URL (Record to PC)  : {base}/audio?token={token}

  Speech API : {t.provider} / {t.model_name}{"" if has_key else "  (no API key: Shortcut B won't work)"}
  AI cleanup : {cleanup}
  Output     : {output.name}

  Check from your iPhone's Safari: {base}/ping?token={token}
  Click into any text box, then run the shortcut on your watch. Ctrl+C stops.
""")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
    return 0


def cmd_send(args: argparse.Namespace) -> int:
    import requests

    cfg = load_config(args.config)
    text = " ".join(args.text)
    print(f"Sending in {args.delay:g} s: click the text box where it should appear...")
    time.sleep(args.delay)
    try:
        resp = requests.post(
            f"http://{args.host}:{cfg.server.port}/text",
            json={"text": text},
            headers={"Authorization": f"Bearer {cfg.server.token}"},
            timeout=15,
        )
    except requests.RequestException as exc:
        print(f"Could not reach WristScribe: {exc}")
        return 1
    print(resp.status_code, resp.text)
    return 0 if resp.ok else 1


def cmd_transcribe(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    transcriber = CloudTranscriber.from_config(cfg.transcription)
    start = time.perf_counter()
    try:
        text = transcriber.transcribe(args.file.read_bytes(), args.file.suffix)
    except (OSError, TranscriptionError) as exc:
        print(f"Failed: {exc}")
        return 1
    print(f"{text}\n({(time.perf_counter() - start):.1f} s via {cfg.transcription.provider})")
    return 0


def cmd_clean(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    cleaner = TextCleaner.from_config(cfg.cleanup, cfg.transcription)
    start = time.perf_counter()
    try:
        text = cleaner.clean(" ".join(args.text))
    except CleanupError as exc:
        print(f"Failed: {exc}")
        return 1
    print(f"{text}\n({(time.perf_counter() - start):.1f} s via {cfg.transcription.provider} / {cleaner.model})")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # `python -m wristscribe` with no command (or only options) means `run`.
    if not argv or (argv[0] not in COMMANDS and argv[0] not in ("-h", "--help", "--version")):
        argv.insert(0, "run")
    args = build_parser().parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s  %(message)s",
        datefmt="%H:%M:%S",
    )
    handlers = {
        "init": cmd_init,
        "run": cmd_run,
        "send": cmd_send,
        "transcribe": cmd_transcribe,
        "clean": cmd_clean,
    }
    try:
        return handlers[args.command](args)
    except ConfigError as exc:
        print(f"Config problem: {exc}")
        return 1
    except RuntimeError as exc:
        print(exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
