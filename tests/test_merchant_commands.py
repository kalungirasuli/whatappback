from src.domain.commands import parse_command, is_merchant_command, COMMANDS


class TestParseCommand:
    def test_register_command_no_args(self):
        result = parse_command("@register")
        assert result == ("register", "")

    def test_register_command_with_whitespace(self):
        result = parse_command("  @register  ")
        assert result == ("register", "")

    def test_post_command_with_args(self):
        result = parse_command("@post Red Dress 50000")
        assert result == ("post", "Red Dress 50000")

    def test_post_command_no_args(self):
        result = parse_command("@post")
        assert result == ("post", "")

    def test_edit_command_with_args(self):
        result = parse_command("@edit 42 name Blue Shirt")
        assert result == ("edit", "42 name Blue Shirt")

    def test_stock_command_with_args(self):
        result = parse_command("@stock 10 25")
        assert result == ("stock", "10 25")

    def test_price_command_with_args(self):
        result = parse_command("@price 5 75000")
        assert result == ("price", "5 75000")

    def test_delete_command_with_args(self):
        result = parse_command("@delete 3")
        assert result == ("delete", "3")

    def test_help_command_no_args(self):
        result = parse_command("@help")
        assert result == ("help", "")

    def test_returns_none_for_plain_text(self):
        result = parse_command("Hello world")
        assert result is None

    def test_returns_none_for_empty_string(self):
        result = parse_command("")
        assert result is None

    def test_returns_none_for_at_without_command(self):
        result = parse_command("@")
        assert result is None

    def test_parse_command_any_at_word(self):
        result = parse_command("@unknown arg1")
        assert result == ("unknown", "arg1")

    def test_returns_none_for_at_without_word(self):
        result = parse_command("@")
        assert result is None

    def test_returns_none_for_no_at_symbol(self):
        result = parse_command("just plain text")
        assert result is None

    def test_case_insensitive_command(self):
        result = parse_command("@REGISTER")
        assert result is not None
        assert result[0] == "register"

    def test_mixed_case_command(self):
        result = parse_command("@Post my item")
        assert result is not None
        assert result[0] == "post"
        assert result[1] == "my item"

    def test_command_with_extra_spaces(self):
        result = parse_command("@post   Red   Dress   50000")
        assert result == ("post", "Red   Dress   50000")

    def test_all_valid_commands(self):
        for cmd in COMMANDS:
            result = parse_command(f"@{cmd}")
            assert result is not None, f"@{cmd} should be parseable"
            assert result[0] == cmd


class TestIsMerchantCommand:
    def test_register_is_merchant_command(self):
        assert is_merchant_command("@register") is True

    def test_post_is_merchant_command(self):
        assert is_merchant_command("@post image caption") is True

    def test_edit_is_merchant_command(self):
        assert is_merchant_command("@edit 1 name value") is True

    def test_stock_is_merchant_command(self):
        assert is_merchant_command("@stock 1 10") is True

    def test_price_is_merchant_command(self):
        assert is_merchant_command("@price 1 50000") is True

    def test_delete_is_merchant_command(self):
        assert is_merchant_command("@delete 1") is True

    def test_help_is_merchant_command(self):
        assert is_merchant_command("@help") is True

    def test_plain_text_not_merchant_command(self):
        assert is_merchant_command("Hello") is False

    def test_empty_string_not_merchant_command(self):
        assert is_merchant_command("") is False

    def test_unknown_command_not_merchant_command(self):
        assert is_merchant_command("@unknown") is False

    def test_partial_command_not_merchant_command(self):
        assert is_merchant_command("@reg") is False

    def test_command_with_leading_space(self):
        assert is_merchant_command("  @register") is True

    def test_at_symbol_only_not_merchant_command(self):
        assert is_merchant_command("@") is False

    def test_register_with_args(self):
        assert is_merchant_command("@register some extra text") is True

    def test_help_with_args(self):
        assert is_merchant_command("@help me") is True

    def test_case_insensitive_detection(self):
        assert is_merchant_command("@REGISTER") is True
        assert is_merchant_command("@Post") is True
        assert is_merchant_command("@HELP") is True
