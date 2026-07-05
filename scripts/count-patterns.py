#!/usr/bin/env python3
"""14가지 AI 티 패턴 + 보조 신호를 본문에서 자동 카운트.

보조 신호:
- 연결어미 뒤 쉼표 (C-11): 6회 이상이면 리듬 #7에 반영
- 문장 길이 편차 stdev (E-1): 감점 없는 참고치
- 3인칭 대명사 남용: 감점 없는 참고치
- 일본어식 쉼표 (문두 접속부사 뒤·주제어 뒤): 감점 없는 참고치 (김한식 2012)
이중 조사(A-19)는 #1 번역투 L2, 양비론 헤징(G-3)은 #9 추측·약화 L2에 흡수.

#1 번역투에는 일본어 계열(일한) 번역투를 함께 잡는다. 한국어와 일본어는
어순이 같고 한자어를 공유해 무의식적 간섭이 크다(김한식 2012, 오경순 2010).

Usage:
    python count-patterns.py <text-file>
    cat text.md | python count-patterns.py
"""

import re
import sys
from collections import defaultdict

PATTERNS = {
    1: {
        "name": "번역투",
        # 일본어 계열(일한) L3: '~에 다름(이) 아니다'(にほかならない). 순한 계산어 아닌 직역 흔적 (김한식 2012, 오경순 2010)
        "L3": [r"~?를 통해", r"~?에 대해", r"~?에 기반하여", r"~?함에 있어", r"~?로 인해", r"되어진다", r"지게 된다",
               r"에 다름\s*(?:이\s*)?아니"],
        # 이중 조사(~으로의/~에서의)는 번역투 고전. im-not-ai A-19에서 흡수 (김정우 2007)
        # ~로부터(from 직역): 김정우 2012(부사격 '-으로부터' 빈출), 김순영 2012. '그로부터'(시간)는 제외
        # 일본어 계열 L2: '~에 있어서'(における), 이중부정 '~지 않으면 안 된다'(なければならない),
        #   '~을 요하다'(を要する), '~에 값하다'(に値する), 낫표 「 ｢(일본어 인용부호) (김한식 2012, 오경순 2010)
        "L2": [r"가지고 있다", r"~?로서의 역할", r"~?을 가능하게 한다", r"~?인 것이다", r"~?는 것이다",
               r"으로의", r"에서의", r"에로의", r"으로부터의", r"(?<=[가-힣])(?<!그)로부터",
               r"에 있어서", r"지 않으면 안\s*[되된될됩됐]", r"[을를] 요(?:하|한다|했|합니|함)", r"에 값하", r"「", r"｢"],
    },
    2: {
        "name": "영어 인용 과다",
        "L3": [r"[가-힣]+\([a-zA-Z][a-zA-Z\s]+\)"],  # 한국어 명사+영어 괄호
        "L2": [],
    },
    3: {
        "name": "기계적 병렬",
        "L3": [r"첫째.*둘째.*셋째"],
        "L2": [],
    },
    4: {
        "name": "관용구·결말 공식",
        "L3": [r"결론적으로", r"시사하는 바가 크다", r"~?할 필요가 있다", r"돌아보게 한다", r"잊지 말아야 한다", r"우리에게 던지는 화두"],
        "L2": [r"혁신적", r"획기적", r"중대한", r"심오한", r"놀라운", r"뜻깊은"],
    },
    5: {
        "name": "피동태 남용",
        "L3": [r"되어진다", r"지게 된다", r"되어지고 있다"],
        # 'by + 행위자' 수동태 직역 '~에 의해/의하여'. 이근희 2005 말뭉치·김정우 2012·김순영 2012
        # 행위자를 주어로 능동 전환. 법률·공식문 표준 용법은 페르소나 층에서 면책
        "L2": [r"에 의해", r"에 의하여"],
    },
    6: {
        "name": "접속사 남발",
        "L3": [],
        # 왜냐하면: because 직역 상투적 종속접속 (김정우 2012). 한국어는 '~때문이다'로 뒤에서 받는다
        "L2": [r"^또한", r"^그러나", r"^한편", r"^더불어", r"^따라서", r"^즉", r"왜냐하면"],
    },
    7: {
        "name": "리듬 균일성",
        "L3": [],
        "L2": [],  # 길이 검사는 별도 로직
    },
    8: {
        "name": "이모지·불릿 과다",
        "L3": [r"[\U0001F300-\U0001FAFF].*[\U0001F300-\U0001FAFF]"],  # 한 단락 이모지 2개+
        "L2": [],
    },
    9: {
        "name": "추측·약화",
        "L3": [r"~?인 것 같다", r"~?인 듯하다", r"~?로 보인다", r"~?라고 할 수 있다", r"~?것 같습니다", r"~?로 보입니다"],
        # 양비론 헤징(결론 회피용 fence-sitting)은 im-not-ai G-3에서 흡수
        "L2": [r"\b조금\b", r"\b살짝\b", r"\b뭔가\b", r"\b되게\b", r"\b약간\b", r"\b꽤\b",
               r"양쪽 모두", r"양측 모두", r"두 가지 모두", r"장점도 있지만", r"장점도 있고", r"균형이 필요"],
    },
    10: {
        "name": "메타·자기해설",
        "L3": [r"이 글에서는", r"정리하자면", r"다시 말해", r"앞서 말했듯이"],
        "L2": [],
    },
    11: {
        "name": "어색한 동사구",
        "L3": [r"달러를 향했", r"로 흘러갔", r"에 다가가고 있", r"를 마주했"],
        "L2": [r"을 그렸"],
    },
    12: {
        "name": "AI 마무리 명언",
        "L3": [
            r"자기 길을 찾는 중",
            r"시대가 왔습니다",
            r"새로운 시대가 열렸",
            r"시간이 시작됐",
            r"신호입니다",
            r"신호로 읽힙니다",
            r"선이 그어지는 자리",
            r"기로에 섰습니다",
            r"중대한 분기점",
            r"한 발 후퇴한 셈",
            r"역사가 어떻게 평가할지",
        ],
        "L2": [r"그림이 분명해졌", r"풍경이 분명해졌", r"베팅이 시장에 등장", r"분위기가 바뀌었"],
    },
    13: {
        "name": "식상한 비유",
        "L3": [
            r"법정에 섰",
            r"법정 공방에 들어섰",
            r"본진이 나섰",
            r"수면 위로 떠올랐",
            r"발길을 돌렸",
            r"포문을 열었",
            r"닻을 올렸",
            r"기지개를 켰",
            r"춘추전국시대",
            r"한 발짝 다가섰",
            r"신호탄을 쏘아 올렸",
            r"도전장을 내밀었",
        ],
        "L2": [r"시동을 걸었", r"엔진을 가동", r"본격 가속", r"급물살", r"드라이브"],
    },
    14: {
        "name": "인용 동사 generic화",
        "L3": [],  # 3회 이상 시 fail (별도 카운트)
        "L2": [r"~?다고 했습니다", r"~?라고 했습니다"],
    },
}

EMDASH_PATTERN = re.compile(r"[—–]")

# 연결어미 직후 쉼표 (im-not-ai C-11, KatFish 4.84배 분리도). 6회 이상이면 강한 AI 신호.
# 동사 연결어미만 노려 '그리고,' 같은 정상 접속부사 쉼표는 피한다.
# 동사·형용사 연결어미(-고/-며/-지만/-면서/-거나) + 쉼표. (?<!그)로 '그리고,' 등 접속부사 제외.
CONNECTIVE_COMMA = re.compile(
    r"(?<!그)(?:[가-힣]고|[가-힣]며|[가-힣]지만|[가-힣]면서|[가-힣]으며|[가-힣]거나),"
)
CONNECTIVE_COMMA_THRESHOLD = 6

# 문장 종결 경계 (참고치 계산용)
SENT_SPLIT = re.compile(r"[.!?]\s|\n")

# 3인칭 대명사 남용 (im-not-ai A-16). 영어 의무 주어를 직역하며 그것/그들/그녀가 잦아짐.
# 김정우 2012(2·3인칭 대명사 빈출)·이희재 2009·김도훈 2009. 감점 없는 참고치.
# '그' 단독은 관형사로 오탐 많아 제외하고, 명백한 대명사형만 센다.
PRONOUN_OVERUSE = re.compile(r"그것|그들|그녀")
PRONOUN_DENSITY_THRESHOLD = 8.0  # 1000자당 8개 이상이면 신호

# 일본어식 쉼표 (김한식 2012). 일본어 독점(讀點)은 문장당 1.49개로 한국어 쉼표(0.36개)의
# 약 4.14배이며, 문두 접속사·부사 뒤와 주제어 '는/은/도' 뒤에 쉼표를 찍는 습관이 있다.
# 이를 그대로 옮기면 쉼표 과잉 번역투가 된다. 감점 없는 참고치.
HEAD_CONJ_COMMA = re.compile(
    r"(?:^|\n)\s*(?:그러나|그리고|그런데|하지만|또한|그러므로|따라서|한편|즉|더불어|그래서),"
)
TOPIC_COMMA = re.compile(r"(?<=[가-힣])(?:은|는|도),")
JP_COMMA_THRESHOLD = 3  # 문두 접속부사 쉼표 + 주제어 쉼표 합계


def pronoun_signal(text: str) -> dict:
    """무생물·3인칭 대명사(그것/그들/그녀) 밀도. 1000자당 임계 초과면 신호."""
    n = len(PRONOUN_OVERUSE.findall(text))
    density = n / max(len(text), 1) * 1000
    return {"count": n, "density": round(density, 1), "flagged": density >= PRONOUN_DENSITY_THRESHOLD}


def connective_comma_signal(text: str) -> dict:
    """연결어미 뒤 쉼표 카운트. 임계값(6회) 이상일 때만 신호로 본다."""
    n = len(CONNECTIVE_COMMA.findall(text))
    return {"count": n, "flagged": n >= CONNECTIVE_COMMA_THRESHOLD}


def jp_comma_signal(text: str) -> dict:
    """일본어식 쉼표(문두 접속부사 뒤 + 주제어 뒤). 감점 없는 참고치 (김한식 2012)."""
    head = len(HEAD_CONJ_COMMA.findall(text))
    topic = len(TOPIC_COMMA.findall(text))
    total = head + topic
    return {"head": head, "topic": topic, "count": total, "flagged": total >= JP_COMMA_THRESHOLD}


def rhythm_stdev(text: str) -> dict:
    """문장 길이 표준편차 (im-not-ai E-1). 감점 아닌 참고치. stdev<8이면 리듬 균일 신호."""
    parts = [s.strip() for s in SENT_SPLIT.split(text) if s.strip()]
    lengths = [len(s) for s in parts]
    if len(lengths) < 4:
        return {"stdev": None, "n": len(lengths), "flagged": False}
    mean = sum(lengths) / len(lengths)
    var = sum((x - mean) ** 2 for x in lengths) / len(lengths)
    stdev = var ** 0.5
    return {"stdev": round(stdev, 1), "n": len(lengths), "flagged": stdev < 8}


def count_patterns(text: str) -> dict:
    """본문에서 14패턴 매칭 카운트."""
    counts = defaultdict(lambda: {"L3": 0, "L2": 0, "matches": defaultdict(list)})

    for num, info in PATTERNS.items():
        for level in ("L3", "L2"):
            for pattern in info[level]:
                matches = re.findall(pattern, text)
                if matches:
                    counts[num][level] += len(matches)
                    counts[num]["matches"][level].extend(matches[:5])  # 최대 5개 예시

    # 인용 동사 generic 반복 검사 (#14 L3)
    generic_count = sum(
        len(re.findall(p, text)) for p in PATTERNS[14]["L2"]
    )
    if generic_count >= 3:
        counts[14]["L3"] += 1  # 3회 이상이면 자동 fail

    # 연결어미 뒤 쉼표 임계 신호 (flagged면 리듬 균일성 #7 L2로 1건 반영)
    conn = connective_comma_signal(text)
    if conn["flagged"]:
        counts[7]["L2"] += 1
        counts[7]["matches"]["L2"].append(f"연결어미 뒤 쉼표 {conn['count']}회")

    # em dash
    emdash_count = len(EMDASH_PATTERN.findall(text))

    return {
        "patterns": dict(counts),
        "emdash": emdash_count,
        "char_count": len(text),
        "connective_comma": conn,
        "rhythm": rhythm_stdev(text),
        "pronoun": pronoun_signal(text),
        "jp_comma": jp_comma_signal(text),
    }


def calculate_score(counts: dict) -> dict:
    """점수 계산식: 10 - L3*2.0 - L2*0.5 - L1*0.2. 가중 한도 적용."""
    total_L3 = sum(c["L3"] for c in counts["patterns"].values())
    total_L2 = sum(c["L2"] for c in counts["patterns"].values())

    # 가중 감점 한도
    L3_deduction = 0
    L2_deduction = 0
    for num, c in counts["patterns"].items():
        L3_deduction += min(c["L3"] * 2.0, 3.0)  # 패턴별 최대 3.0
        L2_deduction += min(c["L2"] * 0.5, 1.5)  # 패턴별 최대 1.5

    score = max(0, 10 - L3_deduction - L2_deduction)

    # 등급
    if score >= 9.0 and total_L3 == 0:
        grade = "A"
    elif score >= 8.0 and total_L3 == 0 and total_L2 <= 4:
        grade = "B"
    elif total_L3 <= 2 or score >= 7.0:
        grade = "C"
    else:
        grade = "D"

    # em dash 자동 fail
    if counts["emdash"] > 0:
        grade = "D (em dash fail)"

    return {
        "score": round(score, 2),
        "grade": grade,
        "total_L3": total_L3,
        "total_L2": total_L2,
        "emdash": counts["emdash"],
    }


def main():
    if len(sys.argv) > 1:
        with open(sys.argv[1], encoding="utf-8") as f:
            text = f.read()
    else:
        text = sys.stdin.read()

    counts = count_patterns(text)
    score_info = calculate_score(counts)

    print(f"=== AI 티 14패턴 진단 ===\n")
    print(f"글자수: {counts['char_count']:,}자")
    print(f"em dash: {counts['emdash']}개\n")

    print("패턴별 카운트:")
    for num, c in sorted(counts["patterns"].items()):
        if c["L3"] > 0 or c["L2"] > 0:
            name = PATTERNS[num]["name"]
            print(f"  {num:2d}. {name:20s} L3={c['L3']} L2={c['L2']}")
            for level in ("L3", "L2"):
                for m in c["matches"][level][:3]:
                    print(f"      {level}: '{m}'")

    # 보조 신호 (참고치)
    conn = counts["connective_comma"]
    rhythm = counts["rhythm"]
    print(f"\n=== 보조 신호 (참고치) ===")
    flag = " ← 6회+ 강한 AI 신호 (리듬 #7 반영)" if conn["flagged"] else ""
    print(f"  연결어미 뒤 쉼표: {conn['count']}회{flag}")
    if rhythm["stdev"] is not None:
        rflag = " ← stdev<8, 문장 길이 균일 (AI 리듬 신호)" if rhythm["flagged"] else ""
        print(f"  문장 길이 편차(stdev): {rhythm['stdev']} (문장 {rhythm['n']}개){rflag}")
    else:
        print(f"  문장 길이 편차: 문장 4개 미만이라 생략")
    pron = counts["pronoun"]
    pflag = " ← 대명사 남용 (영어 주어 직역 신호)" if pron["flagged"] else ""
    print(f"  3인칭 대명사(그것/그들/그녀): {pron['count']}개, 1000자당 {pron['density']}{pflag}")
    jp = counts["jp_comma"]
    jflag = " ← 일본어식 쉼표 과잉 (일한 번역투 신호)" if jp["flagged"] else ""
    print(f"  일본어식 쉼표(문두 접속부사 {jp['head']} + 주제어 뒤 {jp['topic']}): {jp['count']}회{jflag}")

    print(f"\n=== 점수 ===")
    print(f"  L3 합계: {score_info['total_L3']}개")
    print(f"  L2 합계: {score_info['total_L2']}개")
    print(f"  점수: {score_info['score']}/10")
    print(f"  등급: {score_info['grade']}")


if __name__ == "__main__":
    main()
