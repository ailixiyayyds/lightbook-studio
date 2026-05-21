from __future__ import annotations

import re

_VOLUME_PATTERNS = [
    re.compile(r"第\s*\d+\s*卷"),
    re.compile(r"[Vv][Oo][Ll]\.?\s*\d+"),
    re.compile(r"[Vv]\d{1,3}"),
    re.compile(r"卷\s*\d+"),
    re.compile(r"第\s*\d+\s*冊"),
]

_BRACKET_TAGS = [
    re.compile(r"\[[^\]]*?(?:Kome|Kmoe|汉化|自购|DL|扫图|电子版|录入|翻译)[^\]]*\]", re.IGNORECASE),
    re.compile(r"【[^】]*?(?:Kome|Kmoe|汉化|自购|DL|扫图|电子版|录入|翻译)[^】]*】"),
    re.compile(r"（[^）]*?(?:Kome|Kmoe|汉化|自购|DL|扫图|电子版|录入|翻译)[^）]*）"),
]

_PUNCTUATION_RE = re.compile(r"[，,。\.！!？?、；;：:《》「」『』【】（）\(\)\[\]{}〈〉《》\s]+")

_CJK_SIMP_TO_TRAD = {
    "语": "語", "声": "聲", "学": "學", "恋": "戀", "体": "體",
    "过": "過", "开": "開", "游": "遊", "戏": "戲", "轻": "輕",
    "时": "時", "关": "關", "系": "係", "后": "後", "个": "個",
    "里": "裏", "么": "麼", "为": "為", "书": "書", "东": "東",
    "门": "門", "专": "專", "业": "業", "丛": "叢", "举": "舉",
    "乐": "樂", "乡": "鄉", "买": "買", "乱": "亂", "争": "爭",
    "亚": "亞", "产": "產", "亲": "親", "亿": "億", "仅": "僅",
    "从": "從", "仓": "倉", "传": "傳", "伤": "傷", "伦": "倫",
    "伪": "偽", "余": "餘", "众": "眾", "优": "優", "会": "會",
    "长": "長", "广": "廣", "壮": "壯", "复": "復", "处": "處",
    "头": "頭", "实": "實", "写": "寫", "对": "對", "寻": "尋",
    "将": "將", "尔": "爾", "尘": "塵", "尝": "嘗", "岁": "歲",
    "岛": "島", "带": "帶", "帮": "幫", "干": "幹", "并": "並",
    "庄": "莊", "庆": "慶", "应": "應", "忆": "憶", "怀": "懷",
    "战": "戰", "戏": "戲", "户": "戶", "执": "執", "扩": "擴",
    "扫": "掃", "扬": "揚", "扰": "擾", "护": "護", "择": "擇",
    "击": "擊", "拟": "擬", "扩": "擴", "拥": "擁", "拦": "攔",
    "拨": "撥", "择": "擇", "拦": "攔", "拥": "擁",
    "华": "華", "万": "萬", "与": "與", "办": "辦",
}

_CJK_TRAD_TO_SIMP = {v: k for k, v in _CJK_SIMP_TO_TRAD.items()}


def normalize_cjk_title(title: str) -> str:
    text = title.strip()
    text = text.lower()

    for pattern in _BRACKET_TAGS:
        text = pattern.sub("", text)
    for pattern in _VOLUME_PATTERNS:
        text = pattern.sub("", text)

    text = _PUNCTUATION_RE.sub("", text)
    text = re.sub(r"\s+", "", text)

    result_chars: list[str] = []
    for ch in text:
        result_chars.append(_CJK_TRAD_TO_SIMP.get(ch, ch))
    return "".join(result_chars)
