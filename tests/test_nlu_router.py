import pytest

from src.workers.nlu_router import RegexNLURouter, NLUResult


class TestIntentClassification:
    async def test_greeting_hello(self):
        router = RegexNLURouter()
        result = await router.extract("hello")
        assert result.intent == "greeting"

    async def test_greeting_hi(self):
        router = RegexNLURouter()
        result = await router.extract("Hi there!")
        assert result.intent == "greeting"

    async def test_greeting_hey(self):
        router = RegexNLURouter()
        result = await router.extract("hey")
        assert result.intent == "greeting"

    async def test_greeting_good_morning(self):
        router = RegexNLURouter()
        result = await router.extract("good morning")
        assert result.intent == "greeting"

    async def test_search_looking_for(self):
        router = RegexNLURouter()
        result = await router.extract("I am looking for red shoes")
        assert result.intent == "product_search"

    async def test_search_find(self):
        router = RegexNLURouter()
        result = await router.extract("find me a laptop")
        assert result.intent == "product_search"

    async def test_search_do_you_have(self):
        router = RegexNLURouter()
        result = await router.extract("do you have any shirts?")
        assert result.intent == "product_search"

    async def test_search_need(self):
        router = RegexNLURouter()
        result = await router.extract("I need a phone")
        assert result.intent == "product_search"

    async def test_search_want(self):
        router = RegexNLURouter()
        result = await router.extract("I want to buy shoes")
        assert result.intent == "product_search"

    async def test_search_sell_me(self):
        router = RegexNLURouter()
        result = await router.extract("sell me a chair")
        assert result.intent == "product_search"

    async def test_interest_how_much(self):
        router = RegexNLURouter()
        result = await router.extract("how much is the laptop?")
        assert result.intent == "product_search"

    async def test_interest_price(self):
        router = RegexNLURouter()
        result = await router.extract("what is the price of shoes")
        assert result.intent == "product_search"

    async def test_interest_want_to_buy(self):
        router = RegexNLURouter()
        result = await router.extract("tell me the price")
        assert result.intent == "product_search"

    async def test_interest_buy(self):
        router = RegexNLURouter()
        result = await router.extract("can I buy")
        assert result.intent == "product_search"

    async def test_help_keyword(self):
        router = RegexNLURouter()
        result = await router.extract("help")
        assert result.intent == "help"

    async def test_help_how_to(self):
        router = RegexNLURouter()
        result = await router.extract("how to use this?")
        assert result.intent == "help"

    async def test_unknown_message(self):
        router = RegexNLURouter()
        result = await router.extract("random nonsense text abc")
        assert result.intent == "product_search"
        assert "random" in result.entities.get("product_name", "")

    async def test_image_only_no_text(self):
        router = RegexNLURouter()
        result = await router.extract("", has_image=True)
        assert result.intent == "visual_search"

    async def test_image_with_text_no_keywords(self):
        router = RegexNLURouter()
        result = await router.extract("nice shirt", has_image=True)
        assert result.intent == "visual_search"
        assert not result.is_multi_intent

    async def test_empty_text_no_image(self):
        router = RegexNLURouter()
        result = await router.extract("", has_image=False)
        assert result.intent == "unknown"


class TestEntityExtraction:
    async def test_price_single(self):
        router = RegexNLURouter()
        result = await router.extract("phone 50000")
        assert result.entities["price_min"] == 50000
        assert result.entities["price_max"] == 50000

    async def test_price_range(self):
        router = RegexNLURouter()
        result = await router.extract("phone between 50000 and 100000")
        assert result.entities["price_min"] == 50000
        assert result.entities["price_max"] == 100000

    async def test_price_with_ugx(self):
        router = RegexNLURouter()
        result = await router.extract("shoes 100000 UGX")
        assert result.entities["price_max"] == 100000

    async def test_price_with_commas(self):
        router = RegexNLURouter()
        result = await router.extract("laptop 1,500,000")
        assert result.entities["price_max"] == 1500000

    async def test_color_red(self):
        router = RegexNLURouter()
        result = await router.extract("I want red shoes")
        assert result.entities["color"] == "red"

    async def test_color_blue(self):
        router = RegexNLURouter()
        result = await router.extract("blue shirt")
        assert result.entities["color"] == "blue"

    async def test_color_green(self):
        router = RegexNLURouter()
        result = await router.extract("green dress")
        assert result.entities["color"] == "green"

    async def test_color_multiple(self):
        router = RegexNLURouter()
        result = await router.extract("red and blue shoes")
        colors = result.entities["color"]
        assert isinstance(colors, list)
        assert "red" in colors
        assert "blue" in colors

    async def test_category_electronics(self):
        router = RegexNLURouter()
        result = await router.extract("I need a phone")
        assert result.entities["category"] == "electronics"

    async def test_category_clothing(self):
        router = RegexNLURouter()
        result = await router.extract("looking for a jacket")
        assert result.entities["category"] == "clothing"

    async def test_category_shoes(self):
        router = RegexNLURouter()
        result = await router.extract("need new sneakers")
        assert result.entities["category"] == "shoes"

    async def test_category_furniture(self):
        router = RegexNLURouter()
        result = await router.extract("I want a sofa")
        assert result.entities["category"] == "furniture"

    async def test_category_beauty(self):
        router = RegexNLURouter()
        result = await router.extract("any lipstick?")
        assert result.entities["category"] == "beauty"

    async def test_category_accessories(self):
        router = RegexNLURouter()
        result = await router.extract("nice watch for sale")
        assert result.entities["category"] == "accessories"

    async def test_product_name(self):
        router = RegexNLURouter()
        result = await router.extract("I want Nike sneakers")
        assert "product_name" in result.entities
        assert "Nike" in result.entities["product_name"]

    async def test_location(self):
        router = RegexNLURouter()
        result = await router.extract("looking for shoes in Kampala")
        assert result.entities["location"] == "Kampala"

    async def test_location_at(self):
        router = RegexNLURouter()
        result = await router.extract("laptop at Nakasero")
        assert result.entities["location"] == "Nakasero"

    async def test_combined_entities(self):
        router = RegexNLURouter()
        result = await router.extract("red shoes in Kampala 50000")
        assert result.entities.get("color") == "red"
        assert result.entities.get("location") == "Kampala"
        assert result.entities.get("price_max") == 50000
        assert result.entities.get("category") == "shoes"

    async def test_empty_text_no_entities(self):
        router = RegexNLURouter()
        result = await router.extract("")
        assert result.entities == {}

    async def test_no_entities_for_greeting(self):
        router = RegexNLURouter()
        result = await router.extract("hello")
        assert "price_max" not in result.entities


class TestEntityCarryForward:
    """Entities from earlier user turns must survive follow-up messages."""

    async def test_carries_color_and_category(self):
        router = RegexNLURouter()
        result = await router.extract(
            "under 100k",
            history=[{"role": "user", "content": "I want red sneakers"}],
        )
        assert result.entities.get("color") == "red"
        assert result.entities.get("category") == "shoes"
        assert result.entities.get("price_max") == 100000

    async def test_builds_attributes_and_constraints(self):
        router = RegexNLURouter()
        result = await router.extract(
            "under 100k",
            history=[{"role": "user", "content": "I want red sneakers"}],
        )
        merged = result.entities
        assert merged["attributes"]["color"] == "red"
        assert merged["constraints"]["price_max"] == 100000

    async def test_current_message_wins(self):
        router = RegexNLURouter()
        result = await router.extract(
            "blue shoes",
            history=[{"role": "user", "content": "I want red sneakers"}],
        )
        assert result.entities.get("color") == "blue"

    async def test_most_recent_user_turn_wins(self):
        router = RegexNLURouter()
        result = await router.extract(
            "under 200k",
            history=[
                {"role": "user", "content": "red sneakers"},
                {"role": "assistant", "content": "Got it, red sneakers."},
                {"role": "user", "content": "actually black"},
            ],
        )
        assert result.entities.get("color") == "black"
        assert result.entities.get("price_max") == 200000

    async def test_ignores_assistant_turns(self):
        router = RegexNLURouter()
        result = await router.extract(
            "under 100k",
            history=[
                {"role": "assistant", "content": "I want red sneakers"},
                {"role": "user", "content": "I want a phone"},
            ],
        )
        assert result.entities.get("color") is None
        assert result.entities.get("category") == "electronics"

    async def test_no_history_no_change(self):
        router = RegexNLURouter()
        result = await router.extract("red shoes")
        assert "price_max" not in result.entities
        assert result.entities.get("color") == "red"


class TestNLUResult:
    async def test_nlu_result_dataclass(self):
        result = NLUResult(intent="greeting", entities={"key": "val"}, confidence=0.9)
        assert result.intent == "greeting"
        assert result.entities["key"] == "val"
        assert result.confidence == 0.9

    async def test_nlu_result_default_entities(self):
        result = NLUResult(intent="help")
        assert result.entities == {}

    async def test_nlu_result_default_confidence(self):
        result = NLUResult(intent="unknown")
        assert result.confidence == 0.0
