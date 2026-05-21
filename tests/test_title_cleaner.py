from app.ai.title_cleaner import clean_release_title, infer_book_title


def test_clean_release_title_removes_kome_and_volume() -> None:
    assert clean_release_title("[Kome][輕聲密語]卷04") == "輕聲密語"


def test_clean_release_title_removes_kmoe_and_volume() -> None:
    assert clean_release_title("[Kmoe][輕聲密語]卷02") == "輕聲密語"


def test_clean_release_title_removes_scanlation_marker() -> None:
    assert clean_release_title("[汉化][作品名] 第01卷") == "作品名"


def test_clean_release_title_removes_v_suffix() -> None:
    assert clean_release_title("作品名 v04") == "作品名"


def test_clean_release_title_removes_volume_with_chinese_number() -> None:
    assert clean_release_title("作品名 第04卷") == "作品名"


def test_clean_release_title_removes_dl_marker() -> None:
    assert clean_release_title("[DL][作品名]") == "作品名"


def test_clean_release_title_removes_zi_gou_marker() -> None:
    assert clean_release_title("[自购][作品名] 第01卷") == "作品名"


def test_clean_release_title_handles_file_extension() -> None:
    assert clean_release_title("[Kome][輕聲密語]卷04.cbz") == "輕聲密語"


def test_clean_release_title_preserves_clean_title() -> None:
    assert clean_release_title("輕聲密語") == "輕聲密語"


def test_clean_release_title_removes_volume_prefix() -> None:
    assert clean_release_title("Vol.03 作品名") == "作品名"


def test_infer_book_title_uses_volume_number() -> None:
    assert infer_book_title(4, "[Kome][輕聲密語]卷04") == "第 04 卷"


def test_infer_book_title_single_digit_padded() -> None:
    assert infer_book_title(1, "raw title") == "第 01 卷"


def test_infer_book_title_two_digit() -> None:
    assert infer_book_title(12, "raw title") == "第 12 卷"


def test_infer_book_title_none_volume_falls_back_to_cleaned() -> None:
    result = infer_book_title(None, "[Kome][作品名]卷03")
    assert result == "作品名"
