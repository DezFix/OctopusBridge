from __future__ import annotations

import time

from .translator import Translator

SAMPLES = [
    "こんにちは、世界。",
    "私は毎朝七時に起きて、コーヒーを飲みます。",
    "彼女は図書館で本を読んでいます。",
    "このゲームは本当に面白いですね。",
    "明日の会議の資料を準備しなければなりません。",
    "桜が咲く季節が一番好きです。",
    "彼は駅まで走って行きました。",
    "先週末、友達と映画を見に行きました。",
    "日本語の勉強を続けることが大切です。",
    "お腹が空いたので、何か食べたいです。",
]


def run(pair: str = "ja-ru", repeats: int = 3) -> None:
    print(f"Пара: {pair}, прогонов: {repeats}\n")
    tr = Translator(pair=pair)
    tr.translate("ウォームアップ。")
    times = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        results = tr.translate_batch(SAMPLES)
        times.append(time.perf_counter() - t0)
        tr._cache.clear()  # честный замер без попаданий в кэш
    best = min(times)
    chars = sum(len(s) for s in SAMPLES)
    print(f"{len(SAMPLES)} фраз за {best:.3f} c -> "
          f"{len(SAMPLES) / best:.0f} фраз/с, {chars / best:.0f} симв/с")
    for src, dst in zip(SAMPLES, results):
        print(f"  {src}  ->  {dst}")
    print()
    _bench_argos(pair)


def _bench_argos(pair: str) -> None:
    src, tgt = pair.split("-")
    try:
        import argostranslate.translate as at
    except Exception as exc:
        print(f"Argos недоступен для сравнения: {exc}")
        return
    samples = ["こんにちは、世界。", "私は毎朝七時に起きます。"]
    try:
        t0 = time.perf_counter()
        out = [at.translate(s, src, tgt) for s in samples]
        dt = time.perf_counter() - t0
    except Exception as exc:
        print(f"Argos не смог перевести (нет пакета {src}->{tgt}?): {exc}")
        return
    print(f"[argos] {len(samples)} за {dt * 1000:.0f} мс")
    for s, d in zip(samples, out):
        print(f"  {s}  ->  {d}")


if __name__ == "__main__":
    import sys

    pair = sys.argv[1] if len(sys.argv) > 1 else "ja-ru"
    run(pair)
