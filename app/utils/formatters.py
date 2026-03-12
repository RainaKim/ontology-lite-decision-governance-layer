from typing import Optional


def format_krw(amount: Optional[float]) -> str:
    """Format a KRW amount into Korean notation (억/만 원).

    Returns "미정" for None. This is the canonical implementation —
    do not define _fmt_krw in individual service files.
    """
    if amount is None:
        return "미정"
    v = int(amount)
    awk = v // 100_000_000
    man = (v % 100_000_000) // 10_000
    if awk > 0 and man > 0:
        return f"{awk}억 {man:,}만 원"
    if awk > 0:
        return f"{awk}억 원"
    if man > 0:
        return f"{man:,}만 원"
    return f"{v:,}원"
