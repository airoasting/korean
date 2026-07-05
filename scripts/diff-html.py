#!/usr/bin/env python3
"""다듬기 전/후 차이를 HTML로 시각화. 추가는 녹색, 삭제는 빨강 줄.

Usage:
    python diff-html.py <before-file> <after-file> [output-html]
"""

import sys
from difflib import SequenceMatcher
from pathlib import Path

CSS = """
body {
  max-width: 800px; margin: 40px auto; padding: 0 20px;
  font-family: -apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo", "Noto Sans KR", sans-serif;
  line-height: 1.8; color: #222;
}
h1 { font-size: 1.4em; }
.legend { font-size: 0.9em; color: #666; margin-bottom: 20px; }
.legend span { padding: 2px 8px; border-radius: 4px; margin-right: 8px; }
.added { background: #e6ffed; color: #1a7f37; }
.removed { background: #ffebe9; color: #cf222e; text-decoration: line-through; }
.unchanged { color: #222; }
.diff-block { white-space: pre-wrap; padding: 16px; background: #fafafa;
              border-radius: 6px; border: 1px solid #eee; }
.stats { font-size: 0.85em; color: #555; margin: 16px 0; }
.stats td { padding: 4px 12px; }
"""


def diff_to_html(before: str, after: str) -> str:
    """문자 단위 diff를 HTML로 변환."""
    matcher = SequenceMatcher(None, before, after)
    parts = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            parts.append(f'<span class="unchanged">{before[i1:i2]}</span>')
        elif tag == "delete":
            parts.append(f'<span class="removed">{before[i1:i2]}</span>')
        elif tag == "insert":
            parts.append(f'<span class="added">{after[j1:j2]}</span>')
        elif tag == "replace":
            parts.append(f'<span class="removed">{before[i1:i2]}</span>')
            parts.append(f'<span class="added">{after[j1:j2]}</span>')

    return "".join(parts)


def calculate_change_rate(before: str, after: str) -> float:
    """문자 단위 변경률 (%) 계산."""
    matcher = SequenceMatcher(None, before, after)
    matching = sum(b - a for tag, a, b, _, _ in matcher.get_opcodes() if tag == "equal")
    total = len(before)
    if total == 0:
        return 0.0
    return round((1 - matching / total) * 100, 1)


def make_html(before: str, after: str) -> str:
    """전체 HTML 문서 생성."""
    diff_html = diff_to_html(before, after)
    change_rate = calculate_change_rate(before, after)

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<title>다듬기 전후 비교</title>
<style>{CSS}</style>
</head>
<body>
<h1>다듬기 전후 비교</h1>
<p class="legend">
<span class="added">추가</span>
<span class="removed">삭제</span>
<span class="unchanged">유지</span>
</p>

<table class="stats">
<tr><td>원문 글자수:</td><td>{len(before):,}자</td></tr>
<tr><td>다듬은 글자수:</td><td>{len(after):,}자</td></tr>
<tr><td>변경률:</td><td>{change_rate}%</td></tr>
<tr><td>분량 변화:</td><td>{len(after) - len(before):+d}자 ({(len(after)/len(before)-1)*100:+.1f}%)</td></tr>
</table>

<div class="diff-block">{diff_html}</div>
</body>
</html>
"""


def main():
    if len(sys.argv) < 3:
        print("Usage: python diff-html.py <before-file> <after-file> [output-html]")
        sys.exit(1)

    before_path = Path(sys.argv[1])
    after_path = Path(sys.argv[2])
    output_path = (
        Path(sys.argv[3]) if len(sys.argv) > 3 else before_path.parent / "diff.html"
    )

    before = before_path.read_text(encoding="utf-8")
    after = after_path.read_text(encoding="utf-8")

    html = make_html(before, after)
    output_path.write_text(html, encoding="utf-8")
    print(f"diff HTML saved: {output_path}")
    print(f"변경률: {calculate_change_rate(before, after)}%")


if __name__ == "__main__":
    main()
