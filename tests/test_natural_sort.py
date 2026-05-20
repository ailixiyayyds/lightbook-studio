from app.utils.natural_sort import natural_sorted


def test_natural_sorted_orders_numbers_as_numbers() -> None:
    names = ["page10.jpg", "page2.jpg", "page1.jpg", "page01a.jpg"]

    assert natural_sorted(names) == ["page1.jpg", "page01a.jpg", "page2.jpg", "page10.jpg"]
