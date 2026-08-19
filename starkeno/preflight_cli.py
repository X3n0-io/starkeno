"""CLI locale per normalizzare e analizzare Blueprint Preflight strutturati."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import NoReturn, Sequence

from starkeno.preflight_schema import Blueprint, load_blueprint
from starkeno.preflight_service import (
    BlueprintInputError,
    analyze_confirmed,
    normalize_draft,
    write_blueprint_atomic,
)


class _UsageError(ValueError):
    """Errore conciso causato dagli argomenti o dall'input dell'utente."""


class _ParserExit(Exception):
    def __init__(self, status: int, message: str | None) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise _UsageError(f"{self.prog}: error: {message}")

    def exit(self, status: int = 0, message: str | None = None) -> NoReturn:
        raise _ParserExit(status, message)


def _parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(prog="starkeno preflight")
    commands = parser.add_subparsers(dest="command", required=True)

    esempio = commands.add_parser(
        "esempio", help="scrive un Blueprint d'esempio da cui partire")
    esempio.add_argument("--output", type=Path, required=True)

    draft = commands.add_parser("draft", help="valida e normalizza un Draft Blueprint")
    _add_input_arguments(draft)
    draft.add_argument("--format", choices=("json", "yaml"), required=True)
    draft.add_argument("--output", type=Path, required=True)

    analyze = commands.add_parser("analyze", help="analizza un Blueprint confermato")
    _add_input_arguments(analyze)
    analyze.add_argument("--confirmed", action="store_true")
    analyze.add_argument(
        "--format", choices=("json", "yaml", "markdown", "html"), required=True
    )
    analyze.add_argument("--output", type=Path, required=True)
    analyze.add_argument("--samples", type=int, default=1000)
    analyze.add_argument("--seed", type=int)
    return parser


def _add_input_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--input", type=Path)
    parser.add_argument("--input-format", choices=("json", "yaml"))


def _run_esempio(arguments: argparse.Namespace) -> int:
    """Scrive su disco il Blueprint d'esempio spedito col pacchetto.

    Rifiuta di sovrascrivere: chi rilancia il comando del README dopo aver modificato
    l'esempio perderebbe il proprio lavoro senza un segnale, ed e' la forma di difetto
    che questo progetto continua a pagare.
    """
    from starkeno.preflight_esempio import leggi_esempio

    destinazione: Path = arguments.output
    if destinazione.exists():
        raise _UsageError(
            "%s esiste gia': indica un altro percorso, oppure cancellalo tu"
            % destinazione
        )
    destinazione.parent.mkdir(parents=True, exist_ok=True)
    destinazione.write_text(leggi_esempio(), encoding="utf-8")
    print("Esempio scritto: %s" % destinazione)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Esegue la CLI senza propagare le normali uscite di argparse al chiamante."""
    try:
        arguments = _parser().parse_args(argv)
    except _ParserExit as exc:
        if exc.message:
            stream = sys.stdout if exc.status == 0 else sys.stderr
            stream.write(exc.message)
        return exc.status
    except _UsageError as exc:
        _print_user_error(exc)
        return 2

    try:
        if arguments.command == "esempio":
            return _run_esempio(arguments)
        if arguments.command == "draft":
            return _run_draft(arguments)
        return _run_analyze(arguments)
    except _UsageError as exc:
        _print_user_error(exc)
        return 2
    except (OSError, UnicodeError):
        _print_user_error(_UsageError("operazione I/O locale non riuscita"))
        return 2
    except RecursionError:
        # Il lookahead di `preflight_simulate` ricorre a ogni passaggio del ciclo, e
        # oltre un certo numero di traversate sfonda lo stack. E' un limite noto: va
        # detto, non presentato come un errore interno. Misurato il 19/08/2026: regge
        # fino a 150 passaggi, si rompe fra 150 e 200.
        _print_user_error(_UsageError(
            "il Blueprint contiene un ciclo troppo lungo per il simulatore "
            "(`max_traversals` oltre circa 150). Abbassa il limite del ciclo, oppure "
            "descrivi il lavoro con meno passaggi ripetuti."
        ))
        return 2
    except Exception:
        print("Errore interno durante preflight.", file=sys.stderr)
        return 1


def _run_draft(arguments: argparse.Namespace) -> int:
    text, format_hint, source_path, destination = _read_input(arguments)
    try:
        blueprint = normalize_draft(text, format_hint=format_hint)
    except BlueprintInputError as exc:
        raise _UsageError(str(exc)) from exc
    try:
        written = write_blueprint_atomic(
            blueprint, destination, format=arguments.format, source_path=source_path
        )
    except BlueprintInputError as exc:
        raise _UsageError(str(exc)) from exc
    print(f"Draft salvato: {written}")
    return 0


def _run_analyze(arguments: argparse.Namespace) -> int:
    if not arguments.confirmed:
        raise _UsageError("analyze richiede il flag letterale --confirmed")
    _validate_analysis_arguments(arguments)
    text, format_hint, source_path, destination = _read_input(arguments)
    blueprint = _load_input_blueprint(text, format_hint=format_hint)
    confirmed = blueprint.model_copy(
        update={
            "revision": blueprint.revision + 1,
            "parent_revision": blueprint.revision,
            "confirmed": True,
        }
    )
    analysis = analyze_confirmed(
        confirmed,
        samples=arguments.samples,
        seed=arguments.seed,
        source_path=source_path,
    )
    from starkeno.preflight_report import write_analysis

    written = write_analysis(analysis, destination, format=arguments.format)
    print(f"Analisi completata: {written}")
    return 0


def _validate_analysis_arguments(arguments: argparse.Namespace) -> None:
    if not 1 <= arguments.samples <= 10_000:
        raise _UsageError("--samples deve essere compreso tra 1 e 10000")
    if arguments.seed is not None and arguments.seed < 0:
        raise _UsageError("--seed deve essere maggiore o uguale a zero")


def _load_input_blueprint(text: str, *, format_hint: str) -> Blueprint:
    try:
        return load_blueprint(text, format_hint=format_hint)
    except ValueError as exc:
        raise _UsageError(str(exc)) from exc


def _read_input(
    arguments: argparse.Namespace,
) -> tuple[str, str, Path | None, Path]:
    destination = arguments.output.resolve()
    source_path = arguments.input.resolve() if arguments.input is not None else None
    if source_path is not None and source_path == destination:
        raise _UsageError("La destinazione di output non puo coincidere con l'input")

    format_hint = arguments.input_format or _infer_input_format(source_path)
    if source_path is None:
        text = sys.stdin.read()
    else:
        text = source_path.read_text(encoding="utf-8")
    return text, format_hint, source_path, destination


def _infer_input_format(source_path: Path | None) -> str:
    if source_path is None:
        raise _UsageError("--input-format {json,yaml} e obbligatorio quando si legge stdin")
    suffix = source_path.suffix.casefold()
    if suffix == ".json":
        return "json"
    if suffix in {".yaml", ".yml"}:
        return "yaml"
    raise _UsageError(
        "--input-format {json,yaml} e obbligatorio per un suffisso di input ignoto"
    )


def _print_user_error(error: Exception) -> None:
    message = " ".join(str(error).splitlines()).strip() or "input non valido"
    print(f"Errore: {message}", file=sys.stderr)
