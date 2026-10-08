#!/usr/bin/env python3
"""AI 티 18패턴 + 보조 신호를 본문에서 자동 카운트. (v3.1, 2026-10-06)

v3.1에서 바뀐 것 (근거: evals/regression/ 합성 표본·표현 단위 회귀. 표본 수와 held-out 결과는 references/patterns.md "측정기 검증")
- 정규식을 어미 무관 어간으로. '~할 필요가 있습니다', '~것 같습니다', '~다고 했다'를 놓치던 문제.
- 빈도 승격(FREQ). 기사에 흔한 '통해·대해·로 인해', '로 보인다', '것 같다', '필요가 있다'는 한 번은 경고, 몰리면 치명.
- 이중 감점 제거('되어진다'는 #5만). 학술 서지 낫표, 학술·음차 영어 병기, 경제 기사 의인화 관용구 1건 면책.
- 최신 모델 상투 추가: 선택이 아닌 필수, 단순한 X를 넘어, 남은 질문은 하나, 수사 의문 마무리, 'A가 아니라 B' 몰림.
- 담화 신호와 조기 종료 판정(SKILL.md §2의 단일 정의)을 직접 출력.
- --after: 전후 표·변경률(어절 diff)·말투 집계·숫자/영문 보존 점검을 한 번에. 마크다운 코드는 세지 않는다.
- 슬라이드: 받침 ㅆ 과거형 '~었고' 전체, 대조 '~지만' 40자 면책, 짧은 헤드라인 검사, `# ` 문장형 헤드라인으로 장르 판정.

v3에서 바뀐 것
- 15~18번 패턴 추가. Fable 5.1 계열 모델의 실패 방식은 번역투가 아니라 과압축이다.
  15 과압축 헤드라인(슬라이드 장르만), 16 무생물 주어 의인화, 17 은유 주어, 18 압축 조어(참고).
- #2 영어 병기: 고유명사(대문자 시작·약어)는 치명에서 빼고 참고로 센다. 같은 병기가 2회 이상이면 경고.
- .html 입력 지원. 태그를 벗기고 h1~h3와 title/head/action 클래스를 헤드라인 단위로 표시한다.
- 장르 자동 판정(slide/prose). --genre로 강제. 슬라이드 장르는 최악 문장 3개를 함께 낸다.
- --json 출력.

보조 신호(감점 없음): 연결어미 뒤 쉼표(6회+면 #7 반영), 문장 길이 편차, 3인칭 대명사, 일본어식 쉼표.

Usage:
    python count-patterns.py <file.md|file.txt|file.html> [--genre slide|prose] [--json]
    cat text.md | python count-patterns.py
"""

import argparse
import html as html_lib
import json
import re
import sys
from collections import defaultdict

# 받침 ㅆ 음절(했·었·났·켰…). 과거 시제 판별에 쓴다
_SS_FINAL = "".join(chr(c) for c in range(0xAC00, 0xD7A4) if (c - 0xAC00) % 28 == 20)

# v3.1 원칙. 정규식은 어미를 자른 어간으로 쓴다. '~다'만 잡고 '~습니다'·'~어요'·'~음'을 놓치면 안 된다.
# 기사·보도문에서 흔한 표현(통해·대해·로 인해, 것 같다)은 FREQ에서 경고로 세고 몰려 있을 때만 치명으로 올린다.
PATTERNS = {
    1: {
        "name": "번역투",
        # 일본어 계열(일한) L3: '~에 다름(이) 아니다'(にほかならない) (김한식 2012, 오경순 2010)
        # 이중 피동(되어지다·어지게 되다)은 #5에서만 센다(이중 감점 방지)
        "L3": [r"에 기반하여", r"함에 있어", r"에 다름\s*(?:이\s*)?아니"],
        # 이중 조사(~으로의/~에서의) (김정우 2007). ~로부터(from 직역) (김정우 2012, 김순영 2012). '그로부터'(시간)는 제외
        # 일본어 계열 L2: '~에 있어서', 이중부정 '~지 않으면 안 된다', '~을 요하다', '~에 값하다', 낫표
        "L2": [r"가지고 있(?:다|습니다|어요|음)", r"로서의 역할", r"[을를] 가능하게 (?:한|합|했|해)",
               r"[가-힣] 것(?:이다|입니다)(?![가-힣])",
               r"으로의", r"에서의", r"에로의", r"으로부터의", r"(?<=[가-힣])(?<!그)로부터",
               r"(?<![위래안밖옆쪽곳집방층])에 있어서(?! [가-힣]*(?:못|안 ))", r"지 않으면 안\s*[되된될됩됐]", r"[을를] 요(?:하|한다|했|합니|함)", r"에 값하"],  # 낫표는 citation_safe_brackets에서 따로 센다
    },
    2: {
        "name": "영어 인용 과다",
        "L3": [],  # v3: 별도 로직(고유명사 면책). english_gloss_signal 참조
        "L2": [],
    },
    3: {
        "name": "기계적 병렬",
        # 문두 '첫째,·둘째,·셋째,' 세 번. '10월 셋째 주' 같은 날짜 표현은 잡지 않는다
        "L3": [r"(?:^|[.!?]\s|\n)\s*첫째[,\s][\s\S]*?(?:[.!?]\s|\n)\s*둘째[,\s][\s\S]*?(?:[.!?]\s|\n)\s*셋째[,\s]"],
        "L2": [],
    },
    4: {
        "name": "관용구·결말 공식",
        "L3": [r"결론적으로", r"시사하는 바가 크", r"돌아보게 (?:한|합|만든|만듭)",
               r"잊지 말아야 (?:한|합|할)", r"던지는 (?:물음|질문|화두|숙제)", r"우리에게 던지는",
               r"선택이 아닌 필수", r"선택이 아니라 필수"],  # '~할 필요가 있다'는 FREQ(보고서·학술에서 한 번은 정상)
        # 최신 모델 상투: '단순한 X를 넘어', '그 어느 때보다', '중요한 것은', '~것이 바람직하다'
        "L2": [r"혁신적", r"획기적", r"중대한", r"심오한", r"놀라운", r"뜻깊은", r"압도적",
               r"단순(?:한|히) [가-힣 ]{1,15}?[을를]? ?넘어", r"그 어느 때보다", r"(?:^|[\s,])중요한 것은",
               r"것이 바람직하", r"효과적(?:인|으로)", r"이유는 간단하", r"것이 (?:중요합니다|중요하다|중요해요)"],
    },
    5: {
        "name": "피동태 남용",
        # '되어지다' 모든 활용. '~어지게 되다'(만들어지게 된다). '책임을 지게 된다'(지다)는 앞이 어/아가 아니라 잡지 않는다
        "L3": [r"되어[지진집질졌져짐]"],  # 한글은 음절 단위라 '되어진다'의 '진'을 따로 적는다
        # 'by + 행위자' 직역 '~에 의해/의하여' (이근희 2005, 김정우 2012, 김순영 2012). 법률·공식문은 페르소나 층에서 면책
        # '늦어지게 되었습니다'처럼 굳은 '-어지다' 동사 + '-게 되다'는 사람 글(업무 메일)에도 흔해 경고로 둔다
        "L2": [r"에 의해", r"에 의하여", r"[어아여]지게 (?:된다|됩니다|됐|되었|되는)"],
    },
    6: {
        "name": "접속사 남발",
        "L3": [],
        "L2": [r"(?:^|[.!?]\s|\n)또한", r"(?:^|[.!?]\s|\n)그러나", r"(?:^|[.!?]\s|\n)한편",
               r"(?:^|[.!?]\s|\n)더불어", r"(?:^|[.!?]\s|\n)따라서", r"(?:^|[.!?]\s|\n)즉[ ,]", r"(?:^|[.!?]\s|\n)아울러",
               r"(?:^|[.!?]\s|\n)이를 바탕으로", r"(?:^|[.!?]\s|\n)하지만", r"이는 (?:곧|결국)", r"왜냐하면"],
    },
    7: {
        "name": "리듬 균일성",
        "L3": [],
        "L2": [],  # 연결어미 뒤 쉼표 임계에서 반영
    },
    8: {
        "name": "이모지·불릿 과다",
        "L3": [r"[\U0001F300-\U0001FAFF].*[\U0001F300-\U0001FAFF]"],
        "L2": [],
    },
    9: {
        "name": "추측·약화",
        # '것 같다·듯하다'는 FREQ(2회부터 치명). '~로 보인다고 전망했다'(남의 전망 인용)는 잡지 않는다
        "L3": [],  # '~라고 할 수 있다'는 FREQ(칼럼에서 한 번은 사람 글에도 있다)
        "L2": [r"양쪽 모두", r"양측 모두", r"두 가지 모두", r"장점도 있지만", r"장점도 있고", r"균형이 필요"],
    },
    10: {
        "name": "메타·자기해설",
        "L3": [r"이 글에서는", r"정리하자면", r"다시 말해", r"앞서 말했듯이", r"앞서 살펴본 (?:바와 같이|것처럼)"],
        "L2": [r"주목할 (?:만한 )?점은", r"살펴보(?:겠습니다|도록 하겠|자\.)"],
    },
    11: {
        "name": "어색한 동사구",
        "L3": [r"달러를 향했", r"로 흘러갔", r"에 다가가고 있"],
        # '위기를 마주했다'는 사람 글에도 있어 경고. '곡선을 그렸다'는 사실 묘사라 뺀다
        "L2": [r"(?<!곡선)(?<!궤적)(?<!그래프)(?<!그림)을 그렸", r"[을를] 마주(?:했|하고 있|합니다|한다)"],
    },
    12: {
        "name": "AI 마무리 명언",
        "L3": [
            r"자기 길을 찾는 중", r"시대가 왔", r"새로운 시대가 열", r"시간이 시작(?:됐|되었)", r"(?:의|는|란|한) 신호(?:입니다|이다|다)(?![가-힣])",  # '변화의 신호다', '~라는 신호다'. '기각 신호다' 같은 일반 명사는 뺀다
            r"신호로 읽", r"선이 그어지는 자리", r"기로에 섰", r"중대한 분기점", r"한 발 후퇴한 셈",
            r"역사가 어떻게 평가할지", r"남은 (?:질문|과제|숙제|물음)은 하나", r"우리 손에 달려", r"신호로 (?:볼|해석|받아들)",
        ],
        # 수사 의문 마무리는 별도 로직(rhetorical_ending)
        "L2": [r"그림이 분명해졌", r"풍경이 분명해졌", r"베팅이 시장에 등장", r"분위기가 바뀌었",
               r"답은 [^.\n]{0,20}(?:에 있|에 달려)", r"(?:으로|로) 이어질 것(?:입니다|이다)"],
    },
    13: {
        "name": "식상한 비유",
        "L3": [
            r"법정 공방에 들어섰", r"본진이 나섰", r"수면 위로 떠올랐", r"포문을 열었",
            r"닻을 올렸", r"기지개를 켰", r"춘추전국시대", r"한 발짝 다가섰", r"신호탄을 쏘아 올렸", r"도전장을 내밀었",
            r"거스를 수 없는 (?:흐름|대세|물결)",
        ],
        # '법정에 섰다'(피고인), '발길을 돌렸다'(관광객)는 사실 용법이 흔해 경고
        "L2": [r"법정에 섰", r"발길을 돌렸", r"시동을 걸었", r"엔진을 가동", r"본격 가속", r"급물살", r"드라이브를 (?:걸|건)", r"변화의 (?:파도|물결|바람)",
               r"거짓말을 하지 않", r"패러다임(?:의)? 전환", r"판도를 (?:재편|바꾸|바꿨|바꿀|흔들|뒤집)", r"시험대에 (?:올랐|오르|섰)"],
    },
    14: {
        "name": "인용 동사 generic화",
        "L3": [],  # 빈도 로직(GENERIC_QUOTE). 임계는 count_patterns의 #14 블록
        "L2": [],  # 빈도 로직(GENERIC_QUOTE)
    },
    # ---- v3. 과압축 계열 (Fable 5.1 관찰, 2026-09-07 피자 덱 정답지) ----
    15: {
        "name": "과압축 헤드라인",
        "L3": [],  # 슬라이드 장르에서만 별도 로직 (compression_signal)
        "L2": [],
    },
    16: {
        "name": "무생물 주어 의인화",
        # 같은 절 안에 무생물 명사(지표·비용·가격·쿠폰·매장·정책 등)+조사가 있고 그 뒤에 사람 동사가 올 때만 잡는다.
        # "예산이 부족해 장비를 사지 못했다", "삼성전자가 애플을 앞질렀다" 같은 사람·조직·물건 용법은 주어 목록 밖이라 잡지 않는다.
        "L3": [],
        # 장르 무관 경고: '데이터가 말해 준다', '숫자가 증명한다' 같은 LLM 상투 의인화. 경제 기사 관용구는 personification_signal에서 따로 본다
        "L2": [r"(?:데이터|숫자|수치|지표|결과)(?:가|는|이|은) [^.,\n]{0,12}?(?:증명|말해 주|말해 줍|말해 준|말한다|말합니다|웅변)"],
    },
    17: {
        "name": "은유 주어",
        # "갈림길은 정규직 이탈이다", "주범은 인건비다". 은유 명사가 주어이고 뒤에 명사 술어 단정형(~이다/입니다)이 올 때만 잡는다.
        # "주범이 도주했다", "열쇠는 서랍에 있다" 같은 사실 용법은 술어가 달라 잡지 않는다. 슬라이드 치명, 산문 경고.
        "L3": [],
        # '~가 열쇠다/열쇠이며/열쇠가 될 것' (소유격 없이 서술어 자리에 온 은유). 나머지는 metaphor_subject_signal
        "L2": [r"열쇠(?:이며|입니다|이다|다\.|가 될|라는)", r"핵심은 [^.\n]{0,30}것(?:입니다|이다)", r"열쇠는 ",
               r"(?:열쇠|승부처|분수령|변곡점|갈림길|시금석|게임 체인저|격전지|중심축)(?:로|으로|가|이) (?:부상|떠오르|떠올랐|될|됐|되|자리매김)"],
    },
    18: {
        "name": "압축 조어",
        "L3": [],  # 참고 전용. compound_coinage_signal 참조
        "L2": [],
    },
}

# 빈도 승격. 한 번은 사람 글에도 흔해 경고로 세고, 몰려 있으면 치명 1건을 더한다.
# (패턴 번호, 정규식 목록, 치명 승격 최소 횟수, 승격 최소 밀도(1000자당), 문서용 이름)
FREQ = [
    # 기사·보도문 표준 용법이라 1~2회는 경고. 짧은 글에 3회 이상 몰리면 번역투 습관이다
    (1, [r"[을를] 통(?:해|하여)", r"에 대(?:해|하여)", r"로 인(?:해|하여)"], 3, 2.0, "`~를 통해`, `~에 대해`, `~로 인해` (합산)"),
    # 에세이의 화자 태도 '~인 것 같다' 한 번은 정상. 두 번부터 추측 습관
    # 기사의 '~할 것으로 보인다' 전망 한 번도 정상. '~로 보인다고 전망했다'(남의 전망 인용)는 세지 않는다(임계는 이 줄의 숫자)
    # '~할 필요가 있다'는 보고서·학술 결론에서 한 번은 정상. 몰리면 당위 결말 습관(임계는 이 줄의 숫자)
    (4, [r"필요가 있(?:다|습니다|어요|음)(?![가-힣])"], 2, 0.0, "`~할 필요가 있다`"),
    (9, [r"(?:으로|로) 보(?:인다|입니다|여요|임)(?!고)", r"[다라]고 할 수 있(?:다|습니다|음|어요|겠)"], 2, 0.0,
     "`~로 보인다`(남의 전망 인용 `~로 보인다고` 제외), `~라고 할 수 있다` (합산)"),
    # 에세이의 '~인 것 같다'는 화자의 목소리라 몇 번은 정상. AI는 이 어미를 오히려 드물게 쓴다(임계는 이 줄의 숫자)
    (9, [r"것 같(?:다|습니다|아요|음|네요)", r"[인는한] 듯(?:하다|합니다|해요|함)"], 3, 0.0, "`~인 것 같다`, `~인 듯하다` (합산)"),
]

TAIL_CLOSERS = [
    # '~은 결국 ~이다'. '~하는 것은 결국 마을 어르신들이다'처럼 사실을 압축한 꼴(주어가 '것은')은 뺀다
    (re.compile(r"(?<!것)(?:은|는) 결국 [^.\n\d]{2,40}?(?:이다|입니다|[^" + _SS_FINAL + r"\s\d]다)(?=[.\s]|$)"), "정의형 마무리"),
    (re.compile(r"(?:일|문제|힘|답|핵심|본질|비결)은 [^.\n]{2,30}(?:일|것|문제|힘|과정|태도|습관|방식|용기)(?:이다|입니다|이에요)(?=[.\s]|$)"), "정의형 마무리"),
    (re.compile(r"이제 [^.\n]{0,20}(?:할|바꿔야 할|필요한|남은) 것은 [^.\n]{2,30}(?:이다|입니다)"), "당위 마무리"),
    (re.compile(r"누군가는 [^.\n]{2,30}(?:해야|야) (?:한다|합니다)|[^.\n\d]{2,30}에 달(?:려 있(?:다|습니다)|렸다|렸습니다)|남[은는] 것은 [^.\n\d]{1,20}(?:이다|입니다|다)"
                r"|(?:작은 [가-힣]+|습관|변화|인생|성공|성장|기회|위기|진짜 [가-힣]+)(?:이|가|은|는) [^.\n\d]{0,30}(?:바꿉니다|바꾼다|바꿔 놓|만듭니다|만든다)"
                r"|[^.\n\d]{2,30}에서 (?:시작|나온|나옵|비롯)(?:됩니다|된다|합니다|한다|다|니다)"
                r"|(?:이제|지금은) [^.\n\d]{2,30}(?:할|볼|나설) 때(?:다|입니다)"), "격언형 마무리"),
    # 사람 메일에도 흔한 '언제든 편하게 연락 주세요'는 넣지 않는다
    (re.compile(r"정리하여 공유드립니다|(?:의미 있는|유익한|뜻깊은) (?:자리|시간|회의|기회)(?:가|이) (?:될|되기를|되었으면)"), "메일 상투 맺음말"),
    (re.compile(r"(?:두자|하자|보자|보라|보세요|봅시다|하십시오|해 보길|보시길)[.!]?\s*$"), "권유 마무리"),
]
BUZZ_MIN, BUZZ_MIN_SLIDE = 3, 2  # 개조식·장표는 짧아서 두 개부터 몰림으로 본다
BUZZWORDS = re.compile(r"체질 개선|고도화|데이터 기반|패러다임|시너지|선순환|생태계|내재화|밸류업|레버리지|게임 체인저|퀀텀 점프|골든타임|뉴노멀|"
                       r"본격화|가시화|가속화|구체화|심화|체계 구축|필요성 대두|시급한 상황")

GENERIC_QUOTE = [r"[다라][\"'”’]?고 했(?:습니다|다)(?![가-힣])"]

# 수사 의문 마무리. 두 문장 이상인 글의 마지막 두 문장 중 하나가 묻는 꼴이면 경고 1건(#12). 일정·요청 질문은 뺀다
RHETORICAL_END = re.compile(r"(?:까|인가|는가|겠는가|않은가|까요|나요)[?.]?\s*$")  # 실제 질문 여부는 아래 세 정규식으로 가른다
# 실제 요청·일정 질문('목요일 3시는 어떨까요?', '검토해 주실 수 있을까요?')은 수사 의문이 아니다
STRONG_REAL = re.compile(r"\d|[월화수목금토일]요일|오전|오후|님[,은이께]|님\s")  # 날짜·시간·호칭이 든 질문은 실제 질문
RHETORICAL_SUBJECT = re.compile(r"우리|여러분|당신|무엇|어떻게|어디로|왜 ")  # 독자 전체에게 던지는 물음
REAL_QUESTION = re.compile(r"\d|[월화수목금토일]요일|오전|오후|주시|주실|주세요|드릴|드려도|가능하|괜찮|될까요|할까요|미룰까|옮길까|바꿀까|잡을까|보낼까|계신가요|있으신가요|면 어떨까요|게 어떨까요|낫지 않을까요|좋을까요")  # 높임 제안은 메일의 실제 제안. 해라체 '~면 어떨까.'는 독자 권유라 센다

# 'A가 아니라 B' 대구 틀. 몰리면 경고 1건(#3). 임계는 아래 상수(규칙 표에 그대로 나간다)
NOT_A_BUT_B = re.compile(r"(?:[이가] 아니라|[이가] 아닌)\s")
NOT_A_BUT_B_MIN, NOT_A_BUT_B_DENSITY = 2, 2.5

EMDASH_PATTERN = re.compile(r"[—–]")

# 연결어미 직후 쉼표 (im-not-ai C-11). 6회 이상이면 강한 AI 신호. '그리고,' 같은 접속부사는 제외.
CONNECTIVE_COMMA = re.compile(
    r"(?<!그)(?:[가-힣]고|[가-힣]며|[가-힣]지만|[가-힣]면서|[가-힣]으며|[가-힣]거나),"
)
CONNECTIVE_COMMA_THRESHOLD = 6
CONNECTIVE_COMMA_DENSITY = 3.0  # 1000자당. 긴 문서에서 횟수만으로 켜지던 과잉 검출을 막는다

SENT_SPLIT = re.compile(r"[.!?]\s|\n")

PRONOUN_OVERUSE = re.compile(r"그것|그들|그녀")
PRONOUN_DENSITY_THRESHOLD = 8.0

HEAD_CONJ_COMMA = re.compile(
    r"(?:^|\n|[.!?]\s*)\s*(?:그러나|그리고|그런데|하지만|또한|그러므로|따라서|한편|즉|더불어|그래서),"
)
TOPIC_COMMA = re.compile(r"(?<=[가-힣])(?:은|는|도),")
JP_COMMA_THRESHOLD = 3

# ---- v3 신호 정의 ----

# #2 영어 병기. 괄호 안 영어가 고유명사(각 단어 대문자 시작, 또는 6자 이하 대문자 약어)면 면책(참고).
ENGLISH_GLOSS = re.compile(r"([가-힣]+)\(([A-Za-z][A-Za-z\s.&'-]{0,60})\)")
# 한국어 쪽이 일반 명사면 영어가 대문자라도 병기 치명 ("혁신(Innovation)")
# 학술 용어(정렬·정규화·최적화·학습·추론 등)는 첫 도입 병기가 정상이라 넣지 않는다 (genre-rules.md §5)
COMMON_KO = {"혁신", "통찰", "전략", "역량", "가치", "성장", "효율", "경험", "문화", "신뢰", "투명성", "협업",
             "지능", "지식", "정보", "품질", "속도", "규모", "확장", "몰입", "참여",
             "리더십", "비전", "미션", "목표", "성과", "지표", "고객", "시장", "제품", "플랫폼", "생태계", "기회", "위험", "위기"}


def _is_proper_noun(eng: str) -> bool:
    words = [w for w in re.split(r"[\s&-]+", eng.strip()) if w]
    if not words:
        return False
    if all(w.isupper() and len(w) <= 6 for w in words):
        return True  # ICT, EBIT, M&A
    caps = sum(1 for w in words if w[0].isupper())
    return words[0][0].isupper() and caps / len(words) >= 0.5  # Lieven Van der Veken


def english_gloss_signal(text: str) -> dict:
    """영어 병기. 흔한 추상 명사(혁신·통찰·전략 등) 병기는 치명. 그 밖의 병기는 첫 등장 참고, 같은 병기 반복은 경고.

    v3.1: 학술 용어 첫 도입(`정렬(alignment)`)과 음차 설명(`포드(pod)`)은 style-guide·genre-rules가 권하는 용법이라
    치명에서 뺐다. AI 티는 한국어로 충분한 추상 명사에 영어를 덧붙이는 자리다.
    """
    common, proper, repeated = [], [], []
    seen = defaultdict(int)
    for m in ENGLISH_GLOSS.finditer(text):
        ko, eng = m.group(1), m.group(2).strip()
        if ko in COMMON_KO and not _is_proper_noun(eng):
            common.append(m.group(0))
            continue
        if ko in COMMON_KO and eng[:1].isupper() and not eng.isupper():
            common.append(m.group(0))  # 혁신(Innovation)
            continue
        seen[eng.lower()] += 1
        if seen[eng.lower()] >= 2:
            repeated.append(m.group(0))
        else:
            proper.append(m.group(0))
    return {"L3": common, "L2": repeated, "L1": proper}


# #16 무생물 주어 + 사람 동사. 같은 절(쉼표·마침표 전) 25자 안. 주어 목록 밖(사람·조직·물건)은 잡지 않는다.
# '만들다·흔들다·앞지르다·끌어올리다'는 사실 용법이 흔해 일반 목록에서 뺐다. '만들다'는 "성장은 가격이 만들었다"처럼
# 무생물 주제어(은/는) + 무생물 주어(이/가) + 만들 꼴만 잡는다.
INANIMATE = (r"(?:률|비중|비용|성장|매출|이익|수익|지표|격차|쿠폰|가격|앱|매장|인상|절감|하락|상승|투자|정책|제도|"
             r"숫자|수치|전략|시장|경기|물가|금리|환율|실적|점유율|수수료|할인|단가|인건비|임차료|식자재|원가|재고|주문|수요|공급|"
             r"프로세스|캠페인|채널|배민|배달|매출액|영업이익|비율|결제|혜택|서비스|기능|변화|사례|기술|도구|데이터|흐름)")
PERSON_VERBS = (r"(?:발목을 잡|사지 못|벌어 [주준줍]|가려 [주준줍]|갉아먹|잡아먹|짓눌|숨통을|등을 돌|제자리걸음|"
                r"갈 길을 잃|가릅|가른|갈랐|눌렀|누른|누릅|삼켰|삼킵|먹어 치|손을 [들뗐떼]|팔을 걷|무릎을 꿇|고개를 [들내숙]|"
                r"걷어냈|걷어냅|걷어낸|끌어당기|끌어당겼|끌어당깁|사로잡|못 샀|못 산다|못 삽)")
PERSONIFICATION = re.compile(INANIMATE + r"(?:\s?[\d.,%p억만원배]+)?[을를이가은는]\s[^.,\n]{0,25}?" + PERSON_VERBS)
# "성장은 가격이 만들었고", "이익은 사람이 가릅니다"(주제어가 무생물이면 행위자가 사람이어도 지표를 의인화한 문장)
PERSONIFICATION_MAKE = re.compile(INANIMATE + r"[은는]\s(?:[가-힣]+\s){0,2}?" + INANIMATE + r"[이가] 만들")


def personification_signal(text: str) -> list:
    out = [m.group(0).strip() for m in PERSONIFICATION.finditer(text)]
    out += [m.group(0).strip() for m in PERSONIFICATION_MAKE.finditer(text)]
    return out


# #17 은유 주어. 두 묶음으로 나눈다.
# (a) 사실 용법이 거의 없는 순수 은유(갈림길·분수령·승부처·급소·시금석·변곡점·북극성·양날의 검·게임 체인저):
#     주어 + 명사 술어 단정형(~이다/입니다)이면 잡는다. 슬라이드 치명, 산문 경고.
# (b) 사실 용법이 있는 명사(주범·열쇠·촉매·나침반·지렛대·뇌관): 소유격(`정체의 주범은`)이 앞에 올 때만 잡고 한 단계 낮춘다.
#     슬라이드 경고, 산문 참고. "사건의 주범은 김 씨였다" 같은 사실 문장이 슬라이드에서 경고로 남는 한계는 patterns.md에 적었다.
METAPHOR_PURE = r"(?:갈림길|분수령|승부처|급소|시금석|변곡점|북극성|양날의 검|게임 체인저)"
METAPHOR_LITERAL = r"(?:주범|열쇠|촉매제?|나침반|지렛대|뇌관)"
COPULA = r"(?:[^\n.]|\.(?=\d)){0,40}?(?:입니다|이다|였습니다|이었습니다|였다|이었다)(?![가-힣])"  # 소수점(0.8%p)에서 끊기지 않게
# 순수 은유는 술어 꼴과 상관없이 주어 자리에 오면 잡는다("갈림길은 LFP 대응 속도다", "갈림길은 ~가 아니다")
METAPHOR_SUBJECT = re.compile(r"(?:^|[\s,(#])" + METAPHOR_PURE + r"(?:은|는|이|가)\s(?:[^\n.]|\.(?=\d)){0,40}?다(?![가-힣])")
METAPHOR_SUBJECT_LIT = re.compile(r"(?:[가-힣]+의\s|^#?\s*|\n#?\s*)" + METAPHOR_LITERAL + r"(?:은|는|이|가)\s" + COPULA, re.M)


def _free(m, taken) -> bool:
    """이미 다른 패턴이 센 구간과 겹치면 False. 겹치지 않으면 구간을 등록한다(한 표현 이중 감점 방지)."""
    if taken is None:
        return True
    a, b = m.span()
    if any(a < y and x < b for x, y in taken):
        return False
    taken.append((a, b))
    return True


def metaphor_subject_signal(text: str, taken=None) -> dict:
    return {"pure": [m.group(0).strip() for m in METAPHOR_SUBJECT.finditer(text) if _free(m, taken)],
            "literal": [m.group(0).strip() for m in METAPHOR_SUBJECT_LIT.finditer(text) if _free(m, taken)]}


# #17 참고: 정상 용법이 많은 은유 주어. 감점 없음.
SLIDE_METAPHOR = re.compile(r"(?:^|[\s#])(?:승부|엔진|해법|정답)(?:은|는)\s")
METAPHOR_SUBJECT_L1 = re.compile(r"(?:^|[\s,(])(?:관건|해답|출발점|핵심)(?:은|는)\s")

# #18 압축 조어 '~화'. 정착어 목록은 제외. 감점 없는 참고.
COINAGE = re.compile(r"(?<![가-힣])([가-힣]{1,2}화)(?=(?:이|가|는|은|을|를|이지|입니|다|였|로|와|과)\b|[\s.,)])")
COINAGE_WHITELIST = {
    "변화", "강화", "문화", "진화", "심화", "악화", "둔화", "노화", "정화", "동화", "소화", "대화", "영화", "통화",
    "미화", "융화", "순화", "격화", "완화", "경화", "산화", "석화", "탄화", "분화", "부화", "조화", "평화", "회화",
    "전화", "화화", "재화", "은화", "금화", "신화", "장화", "구화", "교화", "청화", "이화", "일화", "만화", "도화",
    "자동화", "표준화", "구조화", "시각화", "최적화", "정상화", "현실화", "상용화", "체계화", "내재화",
    "다양화", "차별화", "세분화", "전문화", "활성화", "무력화", "형식화", "정량화", "정성화", "제도화", "일반화",
    "구체화", "단순화", "고정화", "모듈화", "브랜드화", "자산화", "도구화", "콘텐츠화", "디지털화",
    "민주화", "산업화", "도시화", "세계화", "현지화", "국산화", "노후화", "양극화", "고령화", "저출산화",
    "약화", "방화", "실화", "녹화", "발화", "개화", "퇴화", "진화", "부화", "소화", "환화", "심화", "정화", "합리화", "사회화",
    "무장화", "규제화", "정례화", "공식화", "다변화", "슬림화", "경량화", "첨단화", "융합화", "고급화", "대중화", "보편화",
}
# 정답지에서 나온 압축 조어(`~화`가 아닌 것). 슬라이드 장르에서 참고로 보고한다.
COINAGE_EXTRA = ("잔차", "앱화", "기회손실")


def compound_coinage_signal(text: str) -> list:
    out = []
    for m in COINAGE.finditer(text):
        w = m.group(1)
        if w not in COINAGE_WHITELIST and w not in out:
            out.append(w)
    for w in COINAGE_EXTRA:
        if w in text and w not in out:
            out.append(w)
    return out


# #15 과압축 헤드라인 (슬라이드 장르). 임계는 korean-rules.md §3 게이트 수치와 같다.
# 두 절 결합. 쉼표가 없어도 잡는다. `~고`는 "보고 체계"처럼 명사에 붙는 '고'를 피하려 과거·서술 어간 뒤에서만 본다.
# 과거 시제 '~었고'는 받침 ㅆ 음절 전체로 잡는다(세웠고·앞당겼고·멈췄고). 쉼표가 붙은 '~고,'는 어간과 상관없이 잡는다
CLAUSE_COUPLE = re.compile(r"(?:[" + _SS_FINAL + r"]고|이고|[가-힣]고,|는데|면서|이며|하며|되며),?\s")
# 대조 '~지만·~으나'는 40자 안이면 한 주장(대비)으로 본다. 40자를 넘으면 두 절 결합으로 센다 (korean-rules.md §3 게이트 1)
CLAUSE_CONTRAST = re.compile(r"(?:지만|으나),?\s")
TWO_SUBJECT_GO = re.compile(r"[가-힣](?:이|가|은|는)\s[^,]{1,20}?[가-힣]고\s[^,]{0,12}?[가-힣](?:이|가|은|는)\s")
HEADLINE_MAX = 40    # 게이트 2. 헤드라인 40자 이하
BODY_MAX = 60        # 게이트 2. 본문 문장 60자 이하
UNIT_MIN = 15        # 이보다 짧은 단위는 라벨·숫자로 보고 건너뜀
KO_RATIO_MIN = 0.4   # 한글 비율. 숫자 표·영문 라벨 제외


def _units(text: str, text_mode: bool = False, h1_only: bool = False) -> list:
    """(단위 문자열, 헤드라인 여부) 목록. 줄 단위로 읽고, 한 줄에 문장이 여럿이면 문장으로 쪼갠다.

    헤드라인 표시 규칙. HTML은 h1~h3·title 클래스에 ⟦H⟧가 붙는다. 텍스트 입력은 `#` 헤딩,
    또는 마침표 없이 끝나는 한 문장짜리 줄(80자 이하)을 헤드라인으로 본다(슬라이드 카피를 그대로 붙인 경우).
    """
    units = []
    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            continue
        is_head = False
        if line.startswith("⟦H⟧"):
            if h1_only:
                continue  # 산문 HTML 기사의 h1~h3는 기사 제목·소제목이라 게이트 대상이 아니다
            is_head = True
            line = line[3:].strip()
        elif line.startswith("#"):
            if h1_only and not line.startswith("# "):
                continue  # 산문 문서의 `##` 소제목은 헤드라인 게이트 대상이 아니다
            is_head = True
            line = line.lstrip("#").strip()
        # 텍스트 입력은 `#`로 시작하는 줄만 헤드라인이다. (마침표 유무로 추정하면 불릿·출처·라벨이 헤드라인으로 잡힌다)
        parts = [p.strip() for p in re.split(r"(?<=[^\d\s][.!?])\s+", line) if p.strip()]  # '1. 옵션'의 번호는 문장 끝이 아니다
        two_sentence_head = False
        if is_head and len(parts) > 1:
            # 헤딩 요소에 문장이 둘 이상이면 주장 둘을 한 줄에 둔 것이다. 한 단위로 합쳐 두 절 결합으로 센다.
            two_sentence_head = True
            parts = [" ".join(parts)]
        for p in parts:
            if len(p) < UNIT_MIN and not is_head:  # 헤드라인은 짧아도 검사한다
                continue
            ko = sum(1 for ch in p if "가" <= ch <= "힣")
            if ko / max(len(p), 1) < KO_RATIO_MIN:
                continue
            units.append((p, is_head, two_sentence_head))
    return units


def compression_signal(text: str, text_mode: bool = False, heads_only: bool = False) -> dict:
    """#15. 게이트 1(한 헤드라인 한 주장)·게이트 2(헤드라인 40자·본문 60자)를 그대로 잰다.

    헤드라인이 두 절을 `~고,`로 이으면 치명, 40자를 넘으면 경고. 본문 문장이 60자를 넘으면 경고.
    반환: L3/L2 예시, 최악 단위(점수순), 게이트 위반 건수.
    """
    units = _units(text, text_mode, h1_only=heads_only)
    if heads_only:
        units = [u for u in units if u[1]]
    l3, l2, worst = [], [], []
    gate = {"headline_coupled": 0, "headline_over40": 0, "body_over60": 0}
    for u, is_head, two_sent in units:
        n = len(u)
        coupled = bool(CLAUSE_COUPLE.search(u)) or two_sent or (n > HEADLINE_MAX and bool(CLAUSE_CONTRAST.search(u)))
        if is_head and not coupled:
            # 현재형 '~고'로 주어 둘을 잇는 헤드라인: '가격이 고객을 당기고 원가가 이익을 누른다'
            coupled = bool(TWO_SUBJECT_GO.search(u))
        if is_head and not coupled and n > 30:
            # 명사형 헤드라인의 쉼표 결합: '외형 성장 속 수익성 훼손, 원가·환율 이중 압박 본격화'. 양쪽이 띄어 쓴 구(8자 이상)면 두 주장.
            # 뒤쪽에 주제어(은/는)가 있는 대비('매출 12% 증가, 영업이익은 제자리')는 대조 면책과 같이 본다
            halves = u.split(", ")
            coupled = (len(halves) == 2 and all(len(h) >= 8 and " " in h.strip() for h in halves)
                       and not re.search(r"[가-힣](?:은|는)\s", halves[1])
                       # '일매출 182만원, 전년 대비 4% 감소'처럼 지표와 비교는 한 주장
                       and not re.match(r"\s*(?:전년|전월|전 분기|전분기|전주|작년|지난해)\s?(?:동기\s?)?대비|\s*[\d.,]+\s?(?:%p?|배)\s", halves[1]))
        bad = 0
        if is_head:
            if coupled:
                gate["headline_coupled"] += 1
            if n > HEADLINE_MAX:
                gate["headline_over40"] += 1
            if coupled and not two_sent and n > HEADLINE_MAX:
                l3.append(u); bad = 3      # 연결어미로 두 절을 잇고 40자 초과: 치명
            elif coupled or n > HEADLINE_MAX:
                l2.append(u); bad = 2      # 두 절(문장 둘 포함) 또는 40자 초과 중 하나: 경고. 게이트 위반 건수에는 그대로 잡힌다
        else:
            # 본문 길이 규칙은 문장형 종결(~다/~요/~까)로 끝나는 단위에만 적용한다. 출처·각주·명사형 캡션은 제외.
            sentence_like = bool(re.search(r"(?:다|요|까|죠)[.!?]?$", u)) and not re.match(r"(?:출처|참고|주)\s*[:：]", u)
            if sentence_like and n > BODY_MAX:
                l2.append(u); bad = 1; gate["body_over60"] += 1
        if bad:
            worst.append((bad, n, u, is_head))
    if heads_only:  # 산문의 `# ` 제목은 경고까지만 준다
        l2, l3 = l3 + l2, []
    worst.sort(key=lambda x: (-x[0], -x[1]))
    return {"L3": l3, "L2": l2, "worst": worst, "units": len(units),
            "heads": sum(1 for _, h, _ in units if h), "gate": gate}


def detect_genre(text: str, from_html: bool, raw: str = "") -> str:
    """슬라이드 vs 산문 자동 판정. HTML이면 슬라이드. 텍스트는 마침표 없는 짧은 줄이 절반 이상이면 슬라이드."""
    if from_html and re.search(r'class="[^"]*\b(?:slide|deck|s-cover|deck-stage)', raw):
        return "slide"
    # 텍스트 슬라이드 카피: `#` 헤드라인이 2개 이상이고 문장으로 끝난다(액션 타이틀). 문서의 `## 소제목`은 명사구라 걸리지 않는다
    # 텍스트 슬라이드·장표·개조식. `##` 소제목이 있는 문서(README 같은 마크다운)는 여기서 빼고 아래 일반 판정으로 간다
    raw_lines = [l for l in text.split("\n") if l.strip()]
    heads = [l for l in raw_lines if l.startswith("# ")]
    # 번호 소제목('1. 개요')은 문서 구조라 불릿으로 세지 않는다. 번호 줄은 문장으로 끝나거나 15자 이상일 때만 불릿이다
    bullets = [l for l in raw_lines if re.match(r"\s*[-*•·]\s", l)
               or (re.match(r"\s*\d+[.)]\s", l) and (len(l.strip()) >= 15 or re.search(r"(?:다|요|함|임|음)[.]?$", l)))]
    body = [l for l in raw_lines if l not in heads and l not in bullets]
    has_sections = any(l.startswith("## ") for l in raw_lines)
    if not from_html and not has_sections:
        if heads and len(bullets) >= 2 and len(bullets) >= len(body):
            return "slide"   # 헤드라인 + 불릿 = 장표 (불릿 두어 개 낀 블로그 글은 본문 문단이 더 많아 제외)
        if len(heads) >= 2 and (not body or sum(map(len, body)) / len(body) < 80):
            return "slide"   # 헤드라인 여럿 + 짧은 본문 = 덱 카피 (긴 문단 에세이의 `# ` 절은 제외)
        if len(bullets) >= 4 and len(bullets) >= len(raw_lines) * 0.5:
            return "slide"   # 개조식 보고
    # 마크다운 표·목록·번호 항목은 슬라이드 증거도 산문 증거도 아니라 뺀다 (문서형 .md가 슬라이드로 오판되던 문제)
    lines = [l.replace("⟦H⟧", "").strip() for l in text.split("\n")
             if len(l.replace("⟦H⟧", "").strip()) >= UNIT_MIN and not re.match(r"\s*(?:\||[-*+] |\d+[.)] |>)", l)]
    if len(lines) < 5:
        return "prose"
    no_period = sum(1 for l in lines if not re.search(r"[.!?。]$", l))
    avg = sum(len(l) for l in lines) / len(lines)
    ratio = no_period / len(lines)
    if from_html:
        # 덱은 라벨·헤드라인이 마침표 없이 끝나는 줄이 많다. 기사 HTML은 문단마다 마침표로 끝난다.
        return "slide" if (ratio >= 0.4 and avg < 90) else "prose"
    return "slide" if (ratio >= 0.5 and avg < 80) else "prose"


# 헤드라인 요소: h1~h3, 또는 class 토큰이 title/headline로 끝나는 요소(action-title, cover-title, agenda-title 등).
# subtitle·sub·desc·caption·header(표 머리)는 본문. 부분 문자열 매칭을 줄이려 토큰 끝을 본다.
HEADLINE_TAG = re.compile(r"<(h[1-3])\b[^>]*>(.*?)</\1>", re.S | re.I)
HEADLINE_CLASS_EL = re.compile(
    r"<(p|div|span|a|li|td|th|figcaption)\b[^>]*class=\"(?![^\"]*(?:subtitle|-sub\b|\bsub\b|desc|caption|note|body|src|source|header))"
    r"[^\"]*(?:^|[\s\"-])(?:title|headline)(?=[\s\"])[^\"]*\"[^>]*>(.*?)</\1>",
    re.S | re.I,
)


def _flatten_heading(inner: str) -> str:
    """헤딩 안의 span·br·strong을 공백으로 합쳐 한 줄로 만든다."""
    t = re.sub(r"<br\s*/?>", " ", inner, flags=re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    return " " + re.sub(r"\s+", " ", t).strip() + " "


def html_to_text(src: str) -> str:
    """태그를 벗기고 헤드라인 요소 앞에 ⟦H⟧ 마커를 붙인 줄 단위 텍스트."""
    s = re.sub(r"<(script|style|svg)\b[^>]*>.*?</\1>", "", src, flags=re.S | re.I)
    s = re.sub(r"<!--.*?-->", "", s, flags=re.S)
    # 헤딩은 안쪽 태그를 합쳐 한 줄로 만든 뒤 마커를 붙인다 (span·br로 쪼개지지 않게)
    s = HEADLINE_TAG.sub(lambda m: "\n⟦H⟧" + _flatten_heading(m.group(2)) + "\n", s)
    s = HEADLINE_CLASS_EL.sub(lambda m: "\n⟦H⟧" + _flatten_heading(m.group(2)) + "\n", s)
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"</(p|h[1-6]|li|div|section|article|td|th|tr|figcaption|blockquote|span)>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html_lib.unescape(s)
    lines = []
    for l in s.split("\n"):
        l = re.sub(r"[ \t\u00a0]+", " ", l).strip()
        if l and l != "⟦H⟧":
            lines.append(l)
    return "\n".join(lines)


# ---- 기존 보조 신호 ----

def pronoun_signal(text: str) -> dict:
    n = len(PRONOUN_OVERUSE.findall(text))
    density = n / max(len(text), 1) * 1000
    return {"count": n, "density": round(density, 1), "flagged": density >= PRONOUN_DENSITY_THRESHOLD}


def connective_comma_signal(text: str) -> dict:
    n = len(CONNECTIVE_COMMA.findall(text))
    density = n / max(len(text), 1) * 1000
    return {"count": n, "flagged": n >= CONNECTIVE_COMMA_THRESHOLD and density >= CONNECTIVE_COMMA_DENSITY}


# 일본어 낫표. 한국 학술 인용 관례(「논문」, 《책》)는 면책한다. 연도·겹화살괄호가 같은 줄에 있으면 서지로 본다
CITATION_LINE = re.compile(r"\(?\d{4}[a-z]?\)?[,.)]|《")


def jp_bracket_signal(text: str) -> list:
    out = []
    for line in text.split("\n"):
        if ("「" in line or "｢" in line) and not CITATION_LINE.search(line):
            out += re.findall(r"[「｢][^」｣\n]{0,20}", line)
    return out


def jp_comma_signal(text: str) -> dict:
    head = len(HEAD_CONJ_COMMA.findall(text))
    topic = len(TOPIC_COMMA.findall(text))
    total = head + topic
    return {"head": head, "topic": topic, "count": total, "flagged": total >= JP_COMMA_THRESHOLD}


RHYTHM_MIN_CHARS = 400
RHYTHM_MIN_SENTS = 8


def rhythm_stdev(text: str) -> dict:
    parts = [s.strip() for s in SENT_SPLIT.split(text) if s.strip()]
    lengths = [len(s) for s in parts]
    if len(lengths) < 4:
        return {"stdev": None, "n": len(lengths), "flagged": False}
    mean = sum(lengths) / len(lengths)
    var = sum((x - mean) ** 2 for x in lengths) / len(lengths)
    stdev = var ** 0.5
    long_enough = len(text) >= RHYTHM_MIN_CHARS and len(lengths) >= RHYTHM_MIN_SENTS
    return {"stdev": round(stdev, 1), "n": len(lengths), "flagged": long_enough and stdev < 8}


def count_patterns(text: str, genre: str = "prose", text_mode: bool = False) -> dict:
    """본문에서 18패턴 매칭 카운트."""
    counts = defaultdict(lambda: {"L3": 0, "L2": 0, "matches": defaultdict(list)})
    soft = [0]  # 사람 글에도 한 번은 흔한 AI 상투 경고 수(수사 의문 결말, 결말 자리 '필요가 있다', #13 경고)
    plain = text.replace("⟦H⟧", "")

    # 겹치는 매칭은 한 번만 센다. 더 구체적인 뒤 번호 패턴과 치명이 먼저 가져간다
    # ('우리에게 던지는 화두'가 치명 2건, '핵심은 ~것입니다'가 #1·#17 이중 감점이 되지 않게)
    # #12 마무리 명언은 이름 그대로 끝자리(마지막 두 문장 또는 뒤 25%)에 있을 때만 치명이고, 본문 중간은 경고다
    ends = [m.end() for m in re.finditer(r"[.!?](?:\s|$)|\n", plain.rstrip())]
    tail_start = min(len(plain) * 0.75, ends[-3] if len(ends) >= 3 else 0)
    taken = []
    for num in sorted(PATTERNS, reverse=True):
        info = PATTERNS[num]
        for level in ("L3", "L2"):
            for pattern in info[level]:
                for m in re.finditer(pattern, plain):
                    a, b = m.span()
                    if any(a < y and x < b for x, y in taken):
                        continue
                    taken.append((a, b))
                    lv = "L2" if (num == 12 and level == "L3" and a < tail_start) else level
                    counts[num][lv] += 1
                    if len(counts[num]["matches"][lv]) < 5:
                        g = m.group(0).strip()
                        counts[num]["matches"][lv].append(g if len(g) <= 80 else g[:78] + "…")

    # #2 영어 병기 (고유명사 면책)
    gloss = english_gloss_signal(plain)
    counts[2]["L3"] += len(gloss["L3"]); counts[2]["matches"]["L3"].extend(gloss["L3"][:5])
    counts[2]["L2"] += len(gloss["L2"]); counts[2]["matches"]["L2"].extend(gloss["L2"][:5])

    # 일본어 낫표 (서지 인용 면책)
    jb = jp_bracket_signal(plain)
    counts[1]["L2"] += len(jb); counts[1]["matches"]["L2"].extend(jb[:3])

    # 빈도 승격 (통해·대해·로 인해, 것 같다)
    for num, pats, esc_n, esc_d, _label in FREQ:
        hits = [m.group(0) for p in pats for m in re.finditer(p, plain)]
        if not hits:
            continue
        counts[num]["L2"] += len(hits); counts[num]["matches"]["L2"].extend(hits[:5])
        # 결말 자리(마지막 두 문장)의 '~할 필요가 있다'는 당위 결말이라 1회 면제를 주지 않는다
        exempt = len(hits) if num != 4 else sum(1 for p in pats for m in re.finditer(p, plain) if m.start() < tail_start)
        if num == 4 and len(hits) - exempt == 1:
            soft[0] += 1  # 결말 자리의 '필요가 있다' 한 번
        counts[num]["freq_L2"] = counts[num].get("freq_L2", 0) + exempt
        if len(hits) >= esc_n and len(hits) / max(len(plain), 1) * 1000 >= esc_d:
            # 몰리면 개별 경고를 치명 1건으로 바꾼다(경고와 치명을 겹쳐 깎지 않는다)
            counts[num]["L2"] -= len(hits); counts[num]["freq_L2"] -= exempt
            counts[num]["L3"] += 1
            counts[num]["matches"]["L3"].append(f"{'·'.join(sorted(set(hits)))} {len(hits)}회 몰림")

    # #12 수사 의문 마무리 (마지막 문장)
    last = [s for s in re.split(r"(?<=[.!?])\s+|\n", plain.strip()) if s.strip()]
    tail = [t.strip() for t in last[-2:]]
    q = next((t for t in tail if RHETORICAL_END.search(t) and not STRONG_REAL.search(t)
              and (RHETORICAL_SUBJECT.search(t) or not REAL_QUESTION.search(t))), None)
    if q and len(last) >= 2:  # 한 문장짜리 질문(메시지)은 마무리가 아니다
        soft[0] += 1
        counts[12]["L2"] += 1; counts[12]["matches"]["L2"].append("수사 의문 마무리: " + (q if len(q) <= 60 else "…" + q[-58:]))

    # #12 끝자리 틀 (마지막 두 문장). 정의형 마무리 '~은 결국 ~이다', '이제 ~할 것은 ~이다', 권유·명령 마무리 '~해 두자·~보라·~보세요'
    tail_txt = plain[int(tail_start):] if tail_start else plain
    if len(plain) >= 300:
        for rx, label in TAIL_CLOSERS:
            mm = rx.search(tail_txt)
            if mm:
                counts[12]["L2"] += 1; counts[12]["matches"]["L2"].append(f"{label}: {mm.group(0).strip()[-30:]}")
                break

    # 유행어 몰림 (#4). 하나둘은 사람 보고서에도 있다. 세 개부터 경고
    buzz = sorted({m.group(0) for m in BUZZWORDS.finditer(plain)})
    if len(buzz) >= (BUZZ_MIN_SLIDE if genre == "slide" else BUZZ_MIN):
        counts[4]["L2"] += 1; counts[4]["matches"]["L2"].append("유행어 몰림: " + "·".join(buzz[:5]))

    # #3 'A가 아니라 B' 대구 틀 몰림
    nab = len(NOT_A_BUT_B.findall(plain))
    if nab >= NOT_A_BUT_B_MIN and nab / max(len(plain), 1) * 1000 >= NOT_A_BUT_B_DENSITY:
        counts[3]["L2"] += 1; counts[3]["matches"]["L2"].append(f"'A가 아니라 B' 틀 {nab}회")

    # #16 무생물 주어 의인화. 슬라이드는 1건부터 경고. 산문은 경제 기사 관용구('환율이 수익성을 갉아먹었다')가 흔해 2건부터 센다
    pers = personification_signal(plain)
    if genre == "slide" or len(pers) >= 2:
        counts[16]["L2"] += len(pers); counts[16]["matches"]["L2"].extend(pers[:5])
    meta = metaphor_subject_signal(plain, taken)
    if genre == "slide":
        counts[17]["L3"] += len(meta["pure"]); counts[17]["matches"]["L3"].extend(meta["pure"][:5])
        counts[17]["L2"] += len(meta["literal"]); counts[17]["matches"]["L2"].extend(meta["literal"][:5])
    else:
        counts[17]["L2"] += len(meta["pure"]); counts[17]["matches"]["L2"].extend(meta["pure"][:5])
    metaphor_l1_literal = meta["literal"] if genre != "slide" else []
    if genre == "slide":  # 덱에서만 은유로 보는 주어: '승부는', '성장 엔진은', '해법은'
        sm = [m.group(0).strip() for m in SLIDE_METAPHOR.finditer(plain) if _free(m, taken)]
        counts[17]["L2"] += len(sm); counts[17]["matches"]["L2"].extend(sm[:3])

    # #14 인용 동사 generic 반복. 한두 번은 기사 표준이라 세지 않는다. 3회부터 경고 1건, 5회부터 치명 1건
    generic = [m.group(0) for p in GENERIC_QUOTE for m in re.finditer(p, plain)]
    if len(generic) >= 5:
        counts[14]["L3"] += 1; counts[14]["matches"]["L3"].append(f"'~고 했다' {len(generic)}회")
    elif len(generic) >= 3:
        counts[14]["L2"] += 1; counts[14]["matches"]["L2"].append(f"'~고 했다' {len(generic)}회")

    # #7 연결어미 뒤 쉼표 임계
    conn = connective_comma_signal(plain)
    if conn["flagged"]:
        counts[7]["L2"] += 1
        counts[7]["matches"]["L2"].append(f"연결어미 뒤 쉼표 {conn['count']}회")

    # #15 과압축. 슬라이드 장르는 전체 게이트. 산문이라도 `# ` 헤드라인(단일 장표 보고의 액션 타이틀)은 게이트 1·2를 잰다
    if genre == "slide":
        comp = compression_signal(text, text_mode)
    else:
        comp = compression_signal(text, text_mode, heads_only=True)
        if not comp["heads"]:
            comp = None
    if comp:
        counts[15]["L3"] += len(comp["L3"]); counts[15]["matches"]["L3"].extend(comp["L3"][:5])
        counts[15]["L2"] += len(comp["L2"]); counts[15]["matches"]["L2"].extend(comp["L2"][:5])

    emdash_count = len(EMDASH_PATTERN.findall(plain))

    return {
        "genre": genre,
        "patterns": dict(counts),
        "soft_hits": soft[0] + counts[13]["L2"],
        "emdash": emdash_count,
        "char_count": len("\n".join(l for l in plain.split("\n") if not GREETING.match(l.strip()))),  # 인사·서명 줄은 뺀 길이
        "connective_comma": conn,
        "rhythm": rhythm_stdev(plain),
        "pronoun": pronoun_signal(plain),
        "jp_comma": jp_comma_signal(plain),
        "english_proper": gloss["L1"],
        "metaphor_l1": [m.strip() for m in METAPHOR_SUBJECT_L1.findall(plain)] + metaphor_l1_literal,
        "coinage": compound_coinage_signal(plain),
        "compression": comp,
    }


AI_SIGNATURE = (3, 4, 10, 12, 13, 14, 16, 17)  # #11 '마주했다·그렸다'는 사람 글에도 있어 뺀다


def calculate_score(counts: dict) -> dict:
    """점수 = 10 − 치명×2.0 − 경고×0.5. 패턴별 한도 치명 3.0, 경고 1.5. 참고는 감점 없음."""
    total_L3 = sum(c["L3"] for c in counts["patterns"].values())
    total_L2 = sum(c["L2"] for c in counts["patterns"].values())
    L3_deduction = sum(min(c["L3"] * 2.0, 3.0) for c in counts["patterns"].values())
    L2_deduction = sum(min(c["L2"] * 0.5, 1.5) for c in counts["patterns"].values())
    score = max(0, 10 - L3_deduction - L2_deduction)

    if score >= 9.0 and total_L3 == 0:
        grade = "A"
    elif score >= 8.0 and total_L3 == 0 and total_L2 <= 4:
        grade = "B"
    elif total_L3 >= 3 or score < 7.0:
        grade = "D"
    else:
        grade = "C"
    if counts["emdash"] > 0:
        grade = "D (em dash fail)"

    # 담화 신호. 어휘 점수는 높아도 담화가 번역투인 글(접속사·대명사·쉼표 몰림)을 조기 종료에서 거른다
    p = counts["patterns"]
    discourse = []
    if counts["pronoun"]["flagged"]:
        discourse.append("대명사 밀도")
    if counts["jp_comma"]["flagged"]:
        discourse.append("일본어식 쉼표")
    if counts["connective_comma"]["flagged"]:
        discourse.append("연결어미 쉼표")
    if p.get(6, {}).get("L2", 0) >= 2:
        discourse.append("문두 접속사 2회+")
    if counts["rhythm"]["flagged"]:
        discourse.append("문장 길이 균일")

    # AI 상투 계열 경고. 번역투(#1)·피동(#5)·추측(#9) 경고 한두 개는 사람 글에도 흔하지만,
    # 결말 공식·명언·비유·은유·의인화·대구 틀 경고는 사람 글에서 드물다. 하나라도 있으면 조기 종료를 막는다
    # 빈도 승격 대상 표현의 1회 경고(예: '~할 필요가 있다' 한 번)는 사람 글에도 흔해 상투 경고에서 뺀다
    ai_signature = sorted(n for n in AI_SIGNATURE if p.get(n, {}).get("L2", 0) - p.get(n, {}).get("freq_L2", 0) > 0)
    comp = counts.get("compression")
    gate_left = bool(comp) and gate_total(counts) > 0

    # 조기 종료 후보(SKILL.md §2의 단일 정의): A 등급 + 치명 0 + 담화 신호 0 + AI 상투 경고 0 + em dash 0.
    # 정규식은 매끈한 일반론을 못 본다. 후보가 떠도 GOLD 확정을 거쳐야 "이미 사람 글로 읽힘"으로 끝낸다
    # AI 상투 경고가 정확히 한 건이고 그것이 '사람 글에도 한 번은 흔한 경고'(수사 의문 결말, 결말 자리의 '필요가 있다',
    # 사실 용법이 흔한 비유 #13 경고)이면 '볼 자리'로 넘기고 막지 않는다. 칼럼의 결론 질문, 보고서 결말의 '필요가 있다'처럼
    # 사람 글에도 한 번은 있는 표현이라 정규식이 단독으로 사람 글 판정을 막지 않게 한다. 판단은 GOLD가 한다(SKILL.md §2)
    sig_hits = sum(p[n]["L2"] - p[n].get("freq_L2", 0) for n in ai_signature)
    soft = sig_hits == 1 and counts.get("soft_hits", 0) == 1
    quant_pass = (grade == "A" and total_L3 == 0 and not discourse and (not ai_signature or soft) and not gate_left
                  and counts["emdash"] == 0)
    # 정량 통과는 조기 종료 '후보'일 뿐이다. 정규식은 AI 글을 잡는 데는 쓰지만 사람 글을 확정하지 못한다
    # (4차 held-out에서 깨끗한 AI 글 17/30이 정량 통과). "이미 사람 글로 읽힘" 확정은 GOLD가 적극적 증거로 한다(SKILL.md §2)
    early_exit = quant_pass

    return {"score": round(score, 2), "grade": grade, "total_L3": total_L3, "total_L2": total_L2, "emdash": counts["emdash"],
            "discourse": discourse, "ai_signature": ai_signature, "soft_warning": soft and quant_pass,
            "quant_pass": quant_pass, "early_exit": early_exit}


# 종결체 집계. 문장 끝 어미로 센다 (BLACK 6항 중 '말투' 자동 확인)
_B_FINAL = "".join(chr(c) for c in range(0xAC00, 0xD7A4) if (c - 0xAC00) % 28 == 17)  # 받침 ㅂ 음절(습·합·됩·입…)
ENDING_STYLES = [
    ("~습니다", re.compile(r"(?:[" + _B_FINAL + r"]니다|[" + _B_FINAL + r"]니까)[.!?]?$")),
    ("~어요", re.compile(r"(?<!필)(?<!중)(?<!수)(?<!개)(?<!주)(?<!강)요[.!?]?$")),  # '구축 필요·개선 중요·주요'는 명사형
    ("~다", re.compile(r"[다][.!?]?$")),
    ("명사형·~함", re.compile(r"[가-힣%)\d][.]?$")),  # 개조식: '~함·~임·명사·숫자'로 끝남. 한 종결체로 본다
]


GREETING = re.compile(r"^(?:안녕하세요|안녕하십니까|감사합니다|고맙습니다|수고하세요|수고하십시오|[가-힣]{2,4} 드림|[가-힣]{2,4}\s?(?:올림|배상))[.!]?$")


def single_ending(prof: dict) -> bool:
    """종결체가 하나인가. 개조식이 아닌 글의 명사형 줄(제목·라벨)은 무시한다."""
    total = sum(prof.values())
    styles = {k: v for k, v in prof.items() if v}
    if styles.get("명사형·~함", 0) and styles["명사형·~함"] < total * 0.5:
        styles.pop("명사형·~함")
    return len(styles) <= 1


def ending_profile(text: str) -> dict:
    prof = defaultdict(int)
    for s in re.split(r"(?<=[.!?])\s+|\n", text):
        if s.lstrip().startswith("#") or re.match(r"\s*\d+[.)]\s*\S{1,12}$", s):
            continue  # 헤드라인·번호 소제목은 종결체 집계에서 뺀다
        s = re.sub(r"^\s*[-*•·]\s*", "", s).strip().rstrip("\"'”’)」")
        if GREETING.match(s) or re.search(r"(?:주세요|주십시오|바랍니다)[.!]?$", s):
            continue  # 인사·서명 줄과 요청형('~해 주세요')은 어느 종결체 글에도 섞여 쓰여 집계에서 뺀다
        if len(s) < 6 or not re.search(r"[가-힣]", s):
            continue
        for name, rx in ENDING_STYLES:
            if rx.search(s):
                prof[name] += 1
                break
    return dict(prof)


NUM_TOKEN = re.compile(r"\d[\d,.]*\s?(?:%p|%|배|퍼센트|억|조|만|천|원|달러|명|개|건|년|월|일|분기|시간|점)?")
LATIN_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9.&+-]{1,}")


def preservation_check(before: str, after: str) -> dict:
    """숫자·영문 고유명사 보존 자동 점검. 원문에 있던 토큰이 결과에서 사라졌으면 목록으로 낸다."""
    def norm(tokens):
        return [t.replace(" ", "").rstrip(".,") for t in tokens]
    b_num, a_num = norm(NUM_TOKEN.findall(before)), norm(NUM_TOKEN.findall(after))
    b_lat, a_lat = set(LATIN_TOKEN.findall(before)), set(LATIN_TOKEN.findall(after))
    a_digits = set(re.findall(r"\d[\d,.]*", after))
    missing_num = [t for t in dict.fromkeys(b_num) if t not in a_num and re.match(r"\d[\d,.]*", t).group(0).rstrip(".,") not in a_digits]
    missing_lat = sorted(t for t in b_lat - a_lat if t[0].isupper() or t.isupper())
    added_num = [t for t in dict.fromkeys(a_num) if t not in b_num and re.match(r"\d[\d,.]*", t).group(0).rstrip(".,") not in set(re.findall(r"\d[\d,.]*", before))]
    return {"missing_numbers": missing_num, "missing_latin": missing_lat, "added_numbers": added_num}


JOSA_TAIL = re.compile(r"(?:으로|에서|에게|까지|부터|처럼|보다|이나|이며|라는|이라|은|는|이|가|을|를|에|의|로|와|과|도|만)$")


def new_words(before: str, after: str, k: int = 10) -> list:
    """결과에 새로 들어간 말 후보. 원문 어절의 앞 두 글자와 겹치지 않는 2음절 이상 어간만 낸다(활용·조사 차이는 무시).
    원문에 없는 내용이 끼어들었는지 사람이 눈으로 확인하는 보조 목록이다."""
    def stem(w):
        st = JOSA_TAIL.sub("", w)
        return st if len(st) >= 2 else w  # '성과'의 '과'처럼 조사로 보이는 글자를 잘라 한 글자가 되면 원형을 쓴다
    seen = set()
    for w in re.findall(r"[가-힣]{2,}", before):
        seen.add(w[:2]); seen.add(stem(w)[:2])
    out = []
    for w in re.findall(r"[가-힣]{2,}", after):
        st = stem(w)
        if st[:2] not in seen and w[:2] not in seen and st not in out:
            out.append(st)
    return out[:k]


def content_suspicious(before: str, after: str, rate: float) -> bool:
    """새 말이 원문 어절의 30% 이상이면 내용 추가 의심. 변경률 70% 조건은 500자 이상 글에만 쓴다(짧은 글은 몇 문장만 지워도 비율이 튄다)."""
    n_before = max(len(re.findall(r"[가-힣]{2,}", before)), 1)
    return len(new_words(before, after, k=999)) >= n_before * 0.3 or (len(before) >= 500 and rate >= 70)


def quant_fail_reasons(score_info: dict, counts: dict, before: str = None, after: str = None, rate: float = 0.0) -> list:
    """정량 통과를 막은 실제 이유 목록. 비어 있으면 통과."""
    r = []
    if score_info["grade"] != "A":
        r.append(f"등급 {score_info['grade']}")
    if score_info["total_L3"]:
        r.append(f"치명 {score_info['total_L3']}")
    if score_info["discourse"]:
        r.append("담화 신호(" + ", ".join(score_info["discourse"]) + ")")
    if score_info["ai_signature"] and not score_info.get("soft_warning"):
        r.append("AI 상투 경고(패턴 " + ", ".join(map(str, score_info["ai_signature"])) + "번)")
    g = gate_total(counts)
    if g:
        r.append(f"게이트 위반 {g}")
    if score_info["emdash"]:
        r.append(f"em dash {score_info['emdash']}")
    if after is not None:
        if content_suspicious(before, after, rate):
            r.append("내용 추가 의심")
        added = preservation_check(before, after)["added_numbers"]
        if added:
            r.append("원문에 없는 숫자 " + ", ".join(added[:3]))
        if not single_ending(ending_profile(after)):
            r.append("말투 섞임")
    return r


def change_rate(before: str, after: str) -> float:
    """변경률(%). 어절 단위 diff. 1 − 일치 비율. 긴 글에서도 빠르다."""
    import difflib
    a, b = before.split(), after.split()
    if not a and not b:
        return 0.0
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    return round((1 - sm.ratio()) * 100, 1)


def worst_units(counts: dict, k: int = 3) -> list:
    comp = counts.get("compression")
    if not comp:
        return []
    return [u for _, _, u, _ in comp["worst"][:k]]


def report(counts: dict, score_info: dict) -> str:
    out = []
    label = {"L3": "치명", "L2": "경고"}
    out.append(f"=== AI 티 18패턴 진단 (장르: {counts['genre']}) ===\n")
    out.append(f"글자수: {counts['char_count']:,}자")
    out.append(f"말투: {_fmt_end(ending_profile(counts.get('_text', '')))}")
    out.append(f"em dash: {counts['emdash']}개\n")
    out.append("패턴별 카운트:")
    any_hit = False
    for num, c in sorted(counts["patterns"].items()):
        if c["L3"] > 0 or c["L2"] > 0:
            any_hit = True
            out.append(f"  {num:2d}. {PATTERNS[num]['name']:20s} 치명={c['L3']} 경고={c['L2']}")
            for level in ("L3", "L2"):
                for m in c["matches"][level][:5]:
                    out.append(f"      {label[level]}: '{m}'")
    if not any_hit:
        out.append("  (없음)")

    conn = counts["connective_comma"]; rhythm = counts["rhythm"]
    out.append("\n=== 보조 신호 (감점 없음. 켜지면 담화 신호로 조기 종료를 막는다. 연결어미 쉼표만 #7 경고 1건) ===")
    out.append(f"  연결어미 뒤 쉼표: {conn['count']}회" + (" ← 켜짐 (6회+·1000자당 3회+, #7 경고)" if conn["flagged"] else " (켜짐 기준 6회+·1000자당 3회+)"))
    if rhythm["stdev"] is not None:
        rflag = " ← stdev<8, 문장 길이 균일" if rhythm["flagged"] else (" (짧은 글이라 억제)" if rhythm["stdev"] < 8 else "")
        out.append(f"  문장 길이 편차(stdev): {rhythm['stdev']} (문장 {rhythm['n']}개){rflag}")
    pron = counts["pronoun"]
    out.append(f"  3인칭 대명사: {pron['count']}개, 1000자당 {pron['density']}" + (" ← 대명사 남용" if pron["flagged"] else ""))
    jp = counts["jp_comma"]
    out.append(f"  일본어식 쉼표(문두 {jp['head']} + 주제어 뒤 {jp['topic']}): {jp['count']}회" + (" ← 과잉" if jp["flagged"] else ""))
    if counts["english_proper"]:
        out.append(f"  고유명사 영어 병기(면책): {len(counts['english_proper'])}건, 예 {counts['english_proper'][:3]}")
    if counts["metaphor_l1"]:
        out.append(f"  은유 주어 후보(참고, 감점 없음. 관건·해답·출발점·핵심, 산문의 소유격+주범·열쇠·촉매류): {len(counts['metaphor_l1'])}건")
    if counts["coinage"]:
        out.append(f"  압축 조어 후보(~화): {counts['coinage'][:8]}")
    comp = counts.get("compression")
    if comp:
        g = comp["gate"]
        out.append(f"  슬라이드 단위: {comp['units']}개 (헤드라인 {comp['heads']}개)")
        gv = gate_total(counts)
        e = {"L2": 0, "L3": 0}
        out.append(f"  게이트 위반 {gv}건: 헤드라인 두 절 {g['headline_coupled']}, 헤드라인 40자 초과 {g['headline_over40']}, 본문 60자 초과 {g['body_over60']}, 의인화 {counts['patterns'].get(16, e)['L2']}, 은유 주어 {counts['patterns'].get(17, e)['L3'] + counts['patterns'].get(17, e)['L2']} (조어 후보 {len(counts['coinage'])}건은 참고, 위반에 넣지 않음)")

    out.append("\n=== 점수 ===")
    out.append(f"  치명 합계: {score_info['total_L3']}개")
    out.append(f"  경고 합계: {score_info['total_L2']}개")
    out.append(f"  점수: {score_info['score']}/10")
    out.append(f"  등급: {score_info['grade']}")
    if score_info["discourse"]:
        out.append(f"  담화 신호: {', '.join(score_info['discourse'])} (조기 종료 막음)")
    if score_info["ai_signature"]:
        out.append(f"  AI 상투 경고: 패턴 {', '.join(map(str, score_info['ai_signature']))}번"
                   + (" (한 건이라 막지 않음. GOLD가 볼 자리)" if score_info.get("soft_warning") else " (조기 종료 막음)"))
    reasons = quant_fail_reasons(score_info, counts)
    out.append("  조기 종료 후보(정량 통과): " + ("예. 정규식이 걸 것이 없다는 뜻일 뿐이다. GOLD가 사람 글의 증거를 확인해야 끝낸다 (SKILL.md §2)"
                                          if score_info["early_exit"] else "아니오 (막힌 이유: " + ", ".join(reasons) + ")"))
    out.append("  (이 점수는 정량 하한이다. 합격선 9.7은 페르소나 점수에 적용한다)")

    worst = worst_units(counts)
    if worst:
        out.append("\n=== 최악 문장 3 (먼저 손볼 자리) ===")
        for i, u in enumerate(worst, 1):
            out.append(f"  {i}. ({len(u)}자) {u}")
    return "\n".join(out)


CODE_FENCE = re.compile(r"```.*?```", re.S)
CODE_SPAN = re.compile(r"`[^`\n]+`")


def strip_code(text: str) -> str:
    """마크다운 코드 블록과 인라인 코드는 본문이 아니다. 금지어 예시를 나열한 문서가 스스로 걸리지 않게 뺀다."""
    return CODE_SPAN.sub(" ", CODE_FENCE.sub("\n", text))


def load(path):
    if path:
        with open(path, encoding="utf-8") as f:
            raw = f.read()
        from_html = path.lower().endswith((".html", ".htm")) or raw.lstrip()[:15].lower().startswith(("<!doctype", "<html"))
    else:
        raw = sys.stdin.read()
        from_html = raw.lstrip()[:15].lower().startswith(("<!doctype", "<html"))
    return raw, from_html


def analyze(raw: str, from_html: bool, genre_arg: str = "auto"):
    text = html_to_text(raw) if from_html else strip_code(raw)
    genre = genre_arg if genre_arg != "auto" else detect_genre(text, from_html, raw)
    counts = count_patterns(text, genre, text_mode=not from_html)
    return text, genre, counts, calculate_score(counts)


def gate_total(counts: dict):
    comp = counts.get("compression")
    if not comp:
        return None
    g, p = comp["gate"], counts["patterns"]
    total = g["headline_coupled"] + g["headline_over40"] + g["body_over60"]
    if counts["genre"] == "slide":  # 산문은 헤드라인 게이트만 본다. 의인화·은유는 산문에서 AI 상투 경고로 따로 막는다
        e = {"L2": 0, "L3": 0}
        total += p.get(16, e)["L2"] + p.get(17, e)["L3"] + p.get(17, e)["L2"]
    return total


def payload(genre, counts, score_info):
    return {
        "genre": genre, "score": score_info["score"], "grade": score_info["grade"],
        "L3": score_info["total_L3"], "L2": score_info["total_L2"], "emdash": counts["emdash"],
        "quant_pass": score_info["quant_pass"], "early_exit": score_info["early_exit"], "discourse": score_info["discourse"],
        "endings": ending_profile(counts.get("_text", "")),
        "ai_signature": score_info["ai_signature"],
        "patterns": {str(n): {"name": PATTERNS[n]["name"], "L3": c["L3"], "L2": c["L2"],
                              "matches": c["matches"]["L3"][:5] + c["matches"]["L2"][:5]}
                     for n, c in counts["patterns"].items() if c["L3"] or c["L2"]},
        "worst": worst_units(counts),
        "coinage": counts["coinage"],
        "gate": (dict((counts["compression"] or {}).get("gate") or {}, personification=counts["patterns"].get(16, {"L2": 0})["L2"],
                      metaphor=counts["patterns"].get(17, {"L3": 0})["L3"] + counts["patterns"].get(17, {"L2": 0})["L2"], coinage=len(counts["coinage"]),
                      total=gate_total(counts))
                 if counts["compression"] else None),
    }


def _fmt_end(prof: dict) -> str:
    return " / ".join(f"{k} {v}" for k, v in sorted(prof.items(), key=lambda x: -x[1])) or "판정 불가"


def compare_report(b, a, rate, pres) -> str:
    (bt, _, bc, bs), (at, _, ac, as_) = b, a
    sign = lambda x: f"{x:+d}" if isinstance(x, int) else f"{x:+.1f}"
    rows = [
        "| 측정 | 전 | 후 | 개선 |",
        "|------|----|----|------|",
        f"| 치명 | {bs['total_L3']} | {as_['total_L3']} | {sign(as_['total_L3'] - bs['total_L3'])} |",
        f"| 경고 | {bs['total_L2']} | {as_['total_L2']} | {sign(as_['total_L2'] - bs['total_L2'])} |",
        f"| 점수 | {bs['score']:.1f} | {as_['score']:.1f} | {sign(as_['score'] - bs['score'])} |",
        f"| 등급 | {bs['grade']} | {as_['grade']} | |",
    ]
    gb, ga = gate_total(bc), gate_total(ac)
    if gb is not None:
        rows.append(f"| 게이트 위반 | {gb} | {ga} | {sign(ga - gb)} |")
    out = rows + [
        "",
        f"말투: {_fmt_end(ending_profile(bt))} → {_fmt_end(ending_profile(at))}",
        f"변경률: 약 {rate}%" + (" (500자 미만이라 참고치. 보존 줄로 판정한다)" if len(bt) < 500 else
                                " (30~50% 경고: 필러 제거면 사유를 적는다)" if 30 <= rate < 50 else " (50% 이상: 롤백)" if rate >= 50 else ""),
        f"em dash: {ac['emdash']}개",
        "보존: " + ("숫자·영문 고유명사 모두 남음" if not (pres["missing_numbers"] or pres["missing_latin"]) else
                  f"사라짐 숫자 {pres['missing_numbers']} 영문 {pres['missing_latin']}"),
    ]
    if pres["added_numbers"]:
        out.append(f"추가된 숫자(원문에 없음): {pres['added_numbers']}")
    nw = new_words(bt, at, k=999)
    n_before = max(len(re.findall(r"[가-힣]{2,}", bt)), 1)
    suspicious = content_suspicious(bt, at, rate)
    if suspicious:
        out.append(f"내용 추가 의심: 새 말 {len(nw)}개(원문 어절의 {len(nw) / n_before:.0%}), 변경률 {rate}%. 정량 통과를 막는다. 원문에 없는 내용이 들어갔는지 확인한다")
    if nw:
        shown = nw[:25]
        more = f" 외 {len(nw) - 25}개" if len(nw) > 25 else ""
        out.append(f"새로 들어간 말 {len(nw)}개(원문에 없는 내용인지 눈으로 확인): {', '.join(shown)}{more}")
    left = [f"{PATTERNS[n]['name']}: {', '.join(map(str, c['matches']['L3'][:3] + c['matches']['L2'][:3]))}"
            for n, c in sorted(ac["patterns"].items()) if c["L3"] or c["L2"]]
    if left:
        out.append("남은 자리: " + " | ".join(left))
    if as_["discourse"]:
        out.append("남은 담화 신호: " + ", ".join(as_["discourse"]))
    if as_["ai_signature"]:
        out.append("남은 AI 상투 경고: 패턴 " + ", ".join(map(str, as_["ai_signature"])) + "번")
    reasons = quant_fail_reasons(as_, ac, bt, at, rate)
    out.append("정량 통과: " + ("예" if not reasons else "아니오 (막힌 이유: " + ", ".join(reasons) + ")"))
    return "\n".join(out)


def rules_table() -> str:
    """임계·정의의 정본. 문서는 이 출력을 그대로 붙인다(patterns.md 'rules' 블록). run.py가 어긋남을 검사한다."""
    names = {n: PATTERNS[n]["name"] for n in PATTERNS}
    rows = []
    for n, _pats, k, d, label in FREQ:
        cond = f"{k}회 이상" + (f", 1000자당 {d:g}회 이상" if d else "")
        rows.append(f"| #{n} {names[n]} | {label} | {cond} |")
    freq = "\n".join(rows)
    return f"""| 규칙 | 값 |
|---|---|
| 점수 | 10 − 치명×2.0 − 경고×0.5, 패턴별 한도 치명 3.0·경고 1.5 |
| 등급 A | 9.0 이상, 치명 0 |
| 등급 B | 8.0 이상, 치명 0, 경고 4개 이하 |
| 등급 D | 치명 3개 이상 또는 7.0 미만 (em dash가 있으면 D) |
| 정량 통과 | 등급 A, 치명 0, 담화 신호 0, AI 상투 경고 0(단 사람 글에도 흔한 경고 한 건, 곧 수사 의문 결말·결말 자리 `필요가 있다`·#13 경고뿐이면 막지 않고 "GOLD가 볼 자리"로 넘긴다), 게이트 위반 0, em dash 0. `--after`에서는 내용 추가 의심 0(새 말이 원문 어절의 30% 이상, 또는 500자 이상 글의 변경률 70% 이상), 원문에 없는 숫자 0, 말투 하나(인사·서명 줄과 개조식이 아닌 글의 제목 줄은 빼고 센다)도 조건이다. 막히면 이유를 그대로 출력한다 |
| 조기 종료 후보 | 다듬기 전 정량 통과. 정규식이 걸 것이 없다는 뜻일 뿐이고, GOLD가 사람 글의 적극적 증거를 확인해야 "이미 사람 글로 읽힘"으로 확정된다 |
| AI 상투 경고 패턴 | {', '.join('#' + str(n) for n in AI_SIGNATURE)} (빈도 승격 대상의 1회 경고는 제외, 단 결말 자리의 `필요가 있다`는 포함) |
| 담화 신호 | 대명사 1000자당 {PRONOUN_DENSITY_THRESHOLD:g}+, 일본어식 쉼표 {JP_COMMA_THRESHOLD}+, 연결어미 쉼표 {CONNECTIVE_COMMA_THRESHOLD}+ 이고 1000자당 {CONNECTIVE_COMMA_DENSITY:g}+, 문두 접속사 2+, 문장 길이 stdev 8 미만({RHYTHM_MIN_CHARS}자·{RHYTHM_MIN_SENTS}문장 이상) |
| `A가 아니라 B` 몰림 (#3) | {NOT_A_BUT_B_MIN}회 이상이고 1000자당 {NOT_A_BUT_B_DENSITY:g}회 이상이면 경고 1 |
| 인용 동사 generic (#14) | `~고 했다` 3~4회 경고 1, 5회 이상 치명 1 |
| 마무리 명언 (#12) | 치명 표현도 마지막 두 문장(또는 뒤 25%) 밖이면 경고. 끝자리 틀(정의형·당위·권유·격언형 마무리, 메일 상투 맺음말)은 300자 이상 글에서 경고 1. 수사 의문은 두 문장 이상 글에서 경고 1(숫자·요일·요청 동사가 든 실제 질문은 제외) |
| 유행어 몰림 (#4) | 서로 다른 유행어·압축 명사(`고도화`, `본격화`, `가시화`, `체계 구축` 등)가 산문 {BUZZ_MIN}개, 슬라이드·개조식 {BUZZ_MIN_SLIDE}개 이상이면 경고 1 |
| 슬라이드 게이트 | 헤드라인 {HEADLINE_MAX}자 이하, 본문 문장 {BODY_MAX}자 이하, 두 절 결합 0, 대조 `~지만·~으나`는 {HEADLINE_MAX}자 이하 면책. 산문의 `# ` 제목은 같은 게이트를 경고로만 적용 |
| 장르 slide 판정 | HTML 덱 클래스, 또는 `##` 소제목이 없고 (`# ` 헤드라인+불릿 2개 이상 / `# ` 2개 이상+짧은 본문 / 불릿이 절반 이상인 개조식) |

빈도 승격 (한 번은 경고. 아래 조건이면 그 경고들을 치명 1건으로 바꾼다)

| 패턴 | 표현 | 치명 조건 |
|---|---|---|
{freq}"""


def main():
    ap = argparse.ArgumentParser(description="AI 티 18패턴 자동 카운트 (v3.1)")
    ap.add_argument("file", nargs="?", help="md/txt/html 파일. 없으면 stdin")
    ap.add_argument("--after", help="다듬은 결과 파일. 주면 전후 비교표(§4)·변경률·말투·보존 점검을 한 번에 낸다")
    ap.add_argument("--genre", choices=["slide", "prose", "auto"], default="auto")
    ap.add_argument("--json", action="store_true", help="JSON으로 출력")
    ap.add_argument("--rules", action="store_true", help="임계·정의 표(정본)를 출력하고 끝낸다")
    args = ap.parse_args()
    if args.rules:
        print(rules_table())
        return

    raw, from_html = load(args.file)
    b = analyze(raw, from_html, args.genre)
    b[2]["_text"] = b[0]

    if args.after:
        raw_a, html_a = load(args.after)
        a = analyze(raw_a, html_a, b[1])  # 장르는 원문 판정을 따른다
        a[2]["_text"] = a[0]
        rate = change_rate(b[0], a[0])
        pres = preservation_check(b[0], a[0])
        if args.json:
            print(json.dumps({"before": payload(b[1], b[2], b[3]), "after": payload(a[1], a[2], a[3]),
                              "change_rate": rate, "preservation": pres, "new_words": new_words(b[0], a[0], k=999),
                              "quant_pass": not quant_fail_reasons(a[3], a[2], b[0], a[0], rate),
                              "quant_fail_reasons": quant_fail_reasons(a[3], a[2], b[0], a[0], rate)}, ensure_ascii=False, indent=1))
        else:
            print(compare_report(b, a, rate, pres))
        return

    _, genre, counts, score_info = b
    if args.json:
        print(json.dumps(payload(genre, counts, score_info), ensure_ascii=False, indent=1))
    else:
        print(report(counts, score_info))


if __name__ == "__main__":
    main()
