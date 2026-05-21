from app.ai.title_cleaner import clean_release_title, infer_book_title


def test_clean_release_title_removes_kome_and_volume() -> None:
    assert clean_release_title("[Kome][輕聲密語]卷04") == "輕聲密語"


def test_clean_release_title_removes_kmoe_and_volume() -> None:
    assert clean_release_title("[Kmoe][輕聲密語]卷02") == "輕聲密語"


def test_clean_release_title_removes_scanlation_marker() -> None:
    assert clean_release_title("[汉化][作品名] 第01卷") == "作品名"


def test_clean_release_title_removes_v_suffix() -> None:
    assert clean_release_title("作品名 v04") == "作品名"


def test_infer_book_title_uses_volume_number() -> None:
    assert infer_book_title(4, "[Kome][輕聲密語]卷04") == "第 04 卷"
