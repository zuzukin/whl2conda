from hello import greeting


def test_greeting() -> None:
    assert greeting() == "hello"
