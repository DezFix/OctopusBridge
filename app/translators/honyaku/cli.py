from __future__ import annotations

import argparse
import sys

from . import registry
from .download import is_downloaded, model_root
from .translator import Translator


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="honyaku",
        description="Быстрый офлайн-переводчик японского/английского на русский (CTranslate2).",
    )
    p.add_argument("text", nargs="*", help="текст для перевода")
    p.add_argument("-p", "--pair", default="ja-ru", choices=registry.PAIRS, help="пара языков")
    p.add_argument("-t", "--tier", default="fast", choices=registry.TIERS, help="тир модели")
    p.add_argument("-f", "--file", help="файл: переводится построчно (UTF-8)")
    p.add_argument("-o", "--output", help="файл для результата (только с --file)")
    p.add_argument("--beam", type=int, default=1, help="ширина поиска (больше = лучше, но медленнее)")
    p.add_argument("--threads", type=int, help="число потоков CPU")
    p.add_argument("--download", action="store_true", help="скачать модели для пары/tier и выйти")
    p.add_argument("--models", action="store_true", help="показать скачанные модели и выйти")
    p.add_argument("--bench", action="store_true", help="запустить бенчмарк и выйти")
    return p


def _print_models() -> None:
    root = model_root()
    print(f"Кэш моделей: {root}")
    for tier in registry.TIERS:
        for pair in registry.PAIRS:
            state = "OK" if is_downloaded(tier, pair, root) else "—"
            print(f"  [{tier:4}] {pair:5} {state}")


def _run_file(args, tr) -> None:
    with open(args.file, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    batch = 256
    out_lines = []
    for i in range(0, len(lines), batch):
        chunk = lines[i : i + batch]
        out_lines.extend(tr.translate_batch(chunk))
    text = "\n".join(out_lines) + "\n"
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"Готово: {len(out_lines)} строк -> {args.output}")
    else:
        print(text, end="")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.models:
        _print_models()
        return 0
    if args.download:
        from .download import ensure_model

        out = ensure_model(args.tier, args.pair)
        print(f"Готово: {out}")
        return 0
    if args.bench:
        from .bench import run

        run()
        return 0
    if not args.text and not args.file:
        if sys.stdin.isatty():
            _run_interactive(args)
            return 0
        args.text = [line.rstrip("\n") for line in sys.stdin]
    tr = Translator(pair=args.pair, tier=args.tier, threads=args.threads, beam_size=args.beam)
    if args.file:
        _run_file(args, tr)
        return 0
    for line in tr.translate_batch(args.text):
        print(line)
    return 0


def _run_interactive(args) -> None:
    from . import registry

    tr = Translator(pair=args.pair, tier=args.tier, threads=args.threads, beam_size=args.beam)
    print(f"honyaku: интерактивный режим ({registry.LANG_NAMES[args.pair.split('-')[0]]} -> "
          f"{registry.LANG_NAMES[args.pair.split('-')[1]]}, tier={args.tier}).")
    print("Введите текст и нажмите Enter. Пустая строка или Ctrl+C — выход.\n")
    try:
        while True:
            try:
                text = input("> ").rstrip("\n")
            except EOFError:
                break
            if not text:
                break
            print(tr.translate(text))
    except KeyboardInterrupt:
        pass
    print()