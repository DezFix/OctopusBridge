from __future__ import annotations

import argparse
import json
import sys

from . import registry
from .download import is_downloaded, model_root
from .translator import Translator


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="honyaku",
        description="Офлайн-переводчик на NLLB-200 (CTranslate2, int8).",
    )
    p.add_argument("text", nargs="*", help="текст для перевода")
    p.add_argument("-p", "--pair", default="ja-ru", help="пара языков (например ru-en, ja-ru)")
    p.add_argument("-f", "--file", help="файл: переводится построчно (UTF-8)")
    p.add_argument("-o", "--output", help="файл для результата (только с --file)")
    p.add_argument("--beam", type=int, default=1, help="ширина поиска (больше = лучше, но медленнее)")
    p.add_argument("--threads", type=int, help="число потоков CPU")
    p.add_argument("--fallback", default="source", choices=Translator.FALLBACKS,
                   help="галлюцинации: source (оригинал) | best (beam=4) | off")
    p.add_argument("--glossary", help="JSON-файл глоссария: {\"термин\": \"перевод\"}")
    p.add_argument("--download", action="store_true", help="скачать модель и выйти")
    p.add_argument("--models", action="store_true", help="показать скачанные модели и выйти")
    p.add_argument("--bench", action="store_true", help="запустить бенчмарк и выйти")
    return p


def _print_models() -> None:
    root = model_root()
    print(f"Кэш моделей: {root}")
    for pair in registry.NLLB_CODES:
        state = "OK" if is_downloaded("best", pair, root) else "—"
        print(f"  [best] {pair:5} {state}")


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


def _load_glossary(path: str) -> dict[str, str]:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in data.items()):
        raise ValueError("Глоссарий должен быть JSON-объектом {\"термин\": \"перевод\"}")
    return data


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.models:
        _print_models()
        return 0
    if args.download:
        from .download import ensure_model

        out = ensure_model("best", args.pair)
        print(f"Готово: {out}")
        return 0
    if args.bench:
        from .bench import run

        run(args.pair)
        return 0
    if not args.text and not args.file:
        if sys.stdin.isatty():
            _run_interactive(args)
            return 0
        args.text = [line.rstrip("\n") for line in sys.stdin]
    tr = Translator(
        pair=args.pair,
        threads=args.threads,
        beam_size=args.beam,
        fallback=args.fallback,
        glossary=_load_glossary(args.glossary) if args.glossary else None,
    )
    if args.file:
        _run_file(args, tr)
        return 0
    for line in tr.translate_batch(args.text):
        print(line)
    return 0


def _run_interactive(args) -> None:
    from . import registry

    tr = Translator(
        pair=args.pair,
        threads=args.threads,
        beam_size=args.beam,
        fallback=args.fallback,
        glossary=_load_glossary(args.glossary) if args.glossary else None,
    )
    print(f"honyaku: интерактивный режим ({registry.LANG_NAMES[args.pair.split('-')[0]]} -> "
          f"{registry.LANG_NAMES[args.pair.split('-')[1]]}).")
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