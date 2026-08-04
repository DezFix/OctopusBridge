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


def run(pair: str = "ja-ru", tier: str | None = None, repeats: int = 3) -> None:
    tiers = [tier] if tier else ["fast", "best"]
    print(f"Пара: {pair}, прогонов: {repeats}\n")
    for tier in tiers:
        tr = Translator(pair=pair, tier=tier)
        tr.translate("ウォームアップ。")
        times = []
        for _ in range(repeats):
            t0 = time.perf_counter()
            results = tr.translate_batch(SAMPLES)
            times.append(time.perf_counter() - t0)
        best = min(times)
        chars = sum(len(s) for s in SAMPLES)
        print(f"[{tier}] {len(SAMPLES)} фраз за {best:.3f} c -> "
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

    if len(sys.argv) > 1:
        run(tier=sys.argv[1] if sys.argv[1] in ("fast", "best") else None)
    else:
        run()