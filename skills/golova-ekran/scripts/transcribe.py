#!/usr/bin/env python3
"""Шаг 3 — расшифровка КАЖДОГО сегмента отдельным коротким клипом.

Так, а не одной дорожкой: на всей дорожке Whisper схлопывает фальстарт
с переспросом в одно вхождение, и повтор в тексте не виден. На клипе в две
секунды ему нечем причёсывать.

Заодно меряем громкость каждого сегмента — огрызки без речи ловим по ней,
а не по тексту (на них модель галлюцинирует «Продолжение следует...»).

Нужен запущенный whisper-server. Если его нет — скрипт скажет, как поднять.
"""
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import lib

P = lib.load_project()
URL = os.environ.get("WHISPER_URL", "http://127.0.0.1:8178/inference")
MODEL = os.environ.get("WHISPER_MODEL",
                       os.path.expanduser("~/.whisper-models/ggml-large-v3.bin"))
LANG = getattr(P, "LANG", "ru")
SRC = {t["id"]: t["head"] for t in P.TAKES}


def server_alive():
    r = subprocess.run(["curl", "-s", "-m", "2", "-o", "/dev/null",
                        "-w", "%{http_code}", URL.rsplit("/", 1)[0] + "/"],
                       capture_output=True, text=True)
    return r.stdout.strip() not in ("", "000")


def one(s):
    clips = os.path.join(lib.work_dir(), "clips")
    wav = os.path.join(clips, f"{s['i']:04d}.wav")
    if not os.path.exists(wav):
        lib.run([lib.FF, "-y", "-v", "error", "-ss", f"{s['a']:.3f}",
                 "-t", f"{s['d']:.3f}", "-i", SRC[s["take"]], "-vn",
                 "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", wav])
    vol = lib.sh([lib.FF, "-hide_banner", "-nostats", "-i", wav, "-af",
                  "volumedetect", "-f", "null", "-"]).stderr
    m = re.search(r"mean_volume: (-?[\d.]+)", vol)
    txt = subprocess.run(["curl", "-s", URL, "-F", f"file=@{wav}",
                          "-F", "temperature=0.0", "-F", "response_format=text"],
                         capture_output=True, text=True).stdout.strip()
    return dict(s, txt=" ".join(txt.split()),
                mean=float(m.group(1)) if m else -99.0)


def main():
    if not server_alive():
        sys.stderr.write(
            "✗ whisper-server не отвечает на " + URL + "\n\n"
            "  Подними его (модель грузится один раз, ~330 сегментов ≈ 4 минуты):\n"
            f"    whisper-server -m {MODEL} -l {LANG} --port 8178 -mc 0 -bo 1 -bs 1 -nf\n\n"
            "  Нет модели — скачай ggml-large-v3.bin:\n"
            "    https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3.bin\n"
            "  Флаг -tp серверу не передавай — падает в help.\n")
        raise SystemExit(1)

    segs = lib.read_json("segments.json")
    os.makedirs(os.path.join(lib.work_dir(), "clips"), exist_ok=True)
    with ThreadPoolExecutor(max_workers=4) as ex:
        res = sorted(ex.map(one, segs), key=lambda x: x["i"])
    lib.write_json("transcript.json", res)
    path = os.path.join(lib.work_dir(), "transcript.txt")
    with open(path, "w", encoding="utf-8") as fh:
        for s in res:
            fh.write(f"{s['i']:4d} [{s['take']}] {s['a']:8.2f}+{s['d']:5.2f} "
                     f"{s['mean']:6.1f}дБ  {s['txt']}\n")
    quiet = [s for s in res if s["mean"] < getattr(P, "SCRAP_DB", -40.0)]
    print(f"расшифровано {len(res)} сегментов → {path}")
    print(f"тише {getattr(P, 'SCRAP_DB', -40.0)} дБ: {len(quiet)} — кандидаты в мусор,")
    print("   но НЕ те, что попали в окна play: там это звук плеера, а не тишина")
    print("дальше: прочитай transcript.txt, заполни DROP/TRIM/BW/MODES в project.py")


if __name__ == "__main__":
    main()
