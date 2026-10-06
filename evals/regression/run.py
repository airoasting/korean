#!/usr/bin/env python3
"""측정기 회귀 테스트. 사람 글 과잉 검출률과 AI 글 미검출률, eval 케이스 분기를 한 번에 잰다.

표본은 탐지기 규칙을 보지 않은 별도 에이전트가 썼다(2026-10-06, 합성 표본. 실제 사람 글 정답지는
`evals/fable51-answer-key.md`). 파일 접두어: h·a 01~40 규칙 조정용, x·y 01~20 1차 held-out, p·q 01~30 2차 held-out,
s·t 01~08과 u·v 01~10은 평가 중 SILVER 페르소나가 직접 쓴 표본(SILVER는 규칙을 읽은 상태였다). m·n 01~30은 4차 held-out, k·j 01~30은 6차 held-out. held-out 결과와 신뢰구간은 references/patterns.md "측정기 검증"에 있다.
지금은 모두 조정에 노출됐으므로 이 러너는 회귀 방지용이다. 규칙을 크게 바꾸면 새 held-out을 받아 한 번만 잰다.

정의
- 과잉 검출: 사람 글이 C·D 등급을 받는다 (스킬이 본격 재작업에 들어간다)
- 미검출(정규식 단계): AI 글이 조기 종료 후보(정량 통과)를 받는다. 실제 스킬은 여기에 GOLD 확인이 한 겹 더 있다
  (GOLD 확인까지 포함한 수치는 references/patterns.md "측정기 검증"의 블라인드 판정)
- 관문(실패하면 exit 1): (1) 기준선(baseline.json) 대비 퇴행 0건. 사람 글이 C·D로 떨어지거나 AI 글이 새로 정량 통과하면 퇴행이다.
  (2) eval 분기 (3) 표현 단위 (4) 문서와 코드 규칙 표 일치.
- 전체 과잉 검출·미검출 비율은 참고로 출력한다. 처음 본 held-out을 합치면 정규식 단계 미검출은 오를 수 있고,
  그것은 퇴행이 아니라 정규식의 한계다(사람 글 확정은 GOLD가 한다. references/patterns.md "측정기 검증").
- 의도한 개선으로 기준선을 바꿀 때만 --update-baseline을 쓴다.

Usage:
    python3 evals/regression/run.py [-v]

--split dev|test는 파일 번호의 홀수·짝수로 전체 표본을 나눈다(이력 확인용). 둘 다 규칙 조정에 썼으므로 held-out이 아니다(이력 확인용).
"""

import argparse
import importlib.util
import json
import pathlib
import re
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("cp", ROOT / "scripts" / "count-patterns.py")
cp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cp)

HERE = pathlib.Path(__file__).resolve().parent
MAX_OVER, MAX_MISS = 0.10, 0.20

# eval 케이스 분기 기대값. 조기 종료가 떠야 하는 것은 #3(이미 사람 글로 읽힘)과 #8(시)뿐이다
EVAL_EARLY_EXIT = {3: True, 8: True}


def measure(path: pathlib.Path):
    raw = path.read_text(encoding="utf-8")
    _, genre, counts, s = cp.analyze(raw, False)
    return genre, s


def in_split(name: str, split: str) -> bool:
    n = int("".join(ch for ch in name if ch.isdigit()))
    return split == "all" or (split == "dev") == (n % 2 == 1)


def run_corpus(kind: str, split: str, verbose: bool):
    rows = []
    for f in sorted((HERE / kind).glob("*.txt")):
        if not in_split(f.stem, split):
            continue
        genre, s = measure(f)
        bad = s["grade"][0] in "CD" if kind == "human" else s["early_exit"]
        rows.append((f.name, genre, s, bad))
        if verbose and bad:
            print(f"  [{kind}] {f.name} {genre} {s['score']} {s['grade']} L3={s['total_L3']} L2={s['total_L2']} {s['discourse']}")
    return rows


def run_evals():
    data = json.loads((ROOT / "evals" / "evals.json").read_text(encoding="utf-8"))
    fails = []
    for e in data["evals"]:
        body = e["prompt"].split("\n", 2)[-1]
        _, genre, counts, s = cp.analyze(body, False)
        want = EVAL_EARLY_EXIT.get(e["id"], False)
        if s["early_exit"] != want:
            fails.append(f"eval #{e['id']}: 조기 종료 {s['early_exit']} (기대 {want}), {s['score']} {s['grade']}")
    return fails


def run_cases():
    """표현 단위 회귀 (cases.tsv). 산문 장르로 잰다."""
    fails = []
    for line in (HERE / "cases.tsv").read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#") and "\t" not in line:
            continue
        text, num, want = line.split("\t")
        _, _, counts, _ = cp.analyze(text, False, "prose")
        c = counts["patterns"].get(int(num), {"L3": 0, "L2": 0})
        got = "L3" if c["L3"] else "L2" if c["L2"] else "0"
        if got != want:
            fails.append(f"#{num} 기대 {want} 실제 {got}: {text}")
    return fails


def check_rules_doc():
    """patterns.md의 rules 블록이 코드(--rules)와 같은지. 문서와 코드의 임계가 어긋나지 않게 한다."""
    doc = (ROOT / "references" / "patterns.md").read_text(encoding="utf-8")
    m = re.search(r"<!-- rules:start -->\n(.*?)\n<!-- rules:end -->", doc, re.S)
    if not m:
        return ["patterns.md에 rules 블록이 없다"]
    if m.group(1).strip() != cp.rules_table().strip():
        return ["patterns.md rules 블록이 코드와 다르다. `python3 scripts/count-patterns.py --rules` 출력으로 바꿔 붙인다"]
    return []


def snapshot(human, ai):
    snap = {}
    for name, _g, s, _bad in human:
        snap["human/" + name] = {"cd": s["grade"][0] in "CD", "exit": s["early_exit"]}
    for name, _g, s, _bad in ai:
        snap["ai/" + name] = {"cd": s["grade"][0] in "CD", "exit": s["early_exit"]}
    return snap


def regressions(snap):
    path = HERE / "baseline.json"
    if not path.exists():
        return ["baseline.json이 없다. --update-baseline으로 만든다"]
    base = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for k, now in snap.items():
        was = base.get(k)
        if was is None:
            continue
        if k.startswith("human/") and now["cd"] and not was["cd"]:
            out.append(f"{k}: 사람 글이 C·D로 떨어짐")
        if k.startswith("ai/") and now["exit"] and not was["exit"]:
            out.append(f"{k}: AI 글이 새로 정량 통과")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["dev", "test", "all"], default="all")
    ap.add_argument("-v", action="store_true")
    ap.add_argument("--update-baseline", action="store_true", help="현재 판정을 기준선으로 저장한다")
    args = ap.parse_args()

    t0 = time.perf_counter()
    human = run_corpus("human", args.split, args.v)
    ai = run_corpus("ai", args.split, args.v)
    eval_fails = run_evals()
    case_fails = run_cases()
    dt = time.perf_counter() - t0

    over = sum(r[3] for r in human) / max(len(human), 1)
    miss = sum(r[3] for r in ai) / max(len(ai), 1)
    h_a = sum(r[2]["grade"] == "A" for r in human) / max(len(human), 1)
    a_cd = sum(r[2]["grade"][0] in "CD" for r in ai) / max(len(ai), 1)
    n = len(human) + len(ai) + 13

    print(f"split={args.split}  사람 {len(human)}개 · AI {len(ai)}개 · eval 13건 · {dt * 1000:.0f}ms (글당 {dt / n * 1000:.1f}ms)")
    h_exit = sum(r[2]["early_exit"] for r in human) / max(len(human), 1)
    print(f"  [참고] 과잉 검출(사람 글 C·D): {over:.0%}  참고선 ≤{MAX_OVER:.0%}   | 사람 글 A 비율 {h_a:.0%} · 조기 종료 후보 {h_exit:.0%}")
    print(f"  [참고] 미검출(정규식 단계, AI 글 정량 통과): {miss:.0%}  참고선 ≤{MAX_MISS:.0%}   | AI 글 C·D 비율 {a_cd:.0%}")
    print(f"  eval 분기: {'통과' if not eval_fails else '실패 ' + str(len(eval_fails))}")
    for f in eval_fails:
        print("   ", f)
    n_cases = sum(1 for l in (HERE / "cases.tsv").read_text(encoding="utf-8").splitlines() if "\t" in l)
    print(f"  표현 단위 {n_cases}건: {'통과' if not case_fails else '실패 ' + str(len(case_fails))}")
    for f in case_fails:
        print("   ", f)
    doc_fails = check_rules_doc()
    print(f"  문서-코드 규칙 표 일치: {'통과' if not doc_fails else doc_fails[0]}")
    snap = snapshot(human, ai)
    if args.update_baseline and args.split == "all":
        (HERE / "baseline.json").write_text(json.dumps(snap, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf-8")
        print("  기준선 저장: baseline.json")
    reg = regressions(snap) if args.split == "all" else []
    print("  기준선 대비 퇴행: " + ("검사 생략(--split all에서만 잰다)" if args.split != "all" else ('0건' if not reg else str(len(reg)) + '건')))
    for r in reg[:20]:
        print("   ", r)
    ok = not reg and not eval_fails and not case_fails and not doc_fails
    print("결과:", "통과" if ok else "실패")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
