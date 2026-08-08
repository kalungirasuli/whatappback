from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.llm_nlu import SearchIntent
from src.workers.nlu_router import process_batch


class TestProcessBatch:
    @patch("src.workers.nlu_router.extract_nlu")
    @patch("src.workers.nlu_router.download_media")
    async def test_single_image_no_text(self, mock_dl, mock_extract):
        mock_dl.return_value = b"fake_image_bytes"
        mock_extract.return_value = AsyncMock()
        mock_extract.return_value.search_intents = []
        mock_extract.return_value.intent = "visual_search"

        payload = {
            "from": "+256700000001",
            "images": [{"id": "media_1", "caption": ""}],
            "text": "",
        }

        with (
            patch("src.workers.nlu_router.execute_intent_searches", new_callable=AsyncMock) as mock_exec,
            patch("src.workers.nlu_router.compose_multi_intent_reply", new_callable=AsyncMock, return_value="Here are your matches") as mock_comp,
        ):
            reply = await process_batch(payload)

        assert reply == "Here are your matches"
        mock_exec.assert_awaited_once()
        args = mock_exec.call_args
        intents = args[0][0]
        assert len(intents) == 1
        assert intents[0].type == "visual_search"
        assert "Image 1" in intents[0].description

    @patch("src.workers.nlu_router.extract_nlu")
    @patch("src.workers.nlu_router.download_media")
    async def test_multiple_images_no_text(self, mock_dl, mock_extract):
        mock_dl.return_value = b"img_bytes"
        mock_extract.return_value = AsyncMock()
        mock_extract.return_value.search_intents = []
        mock_extract.return_value.intent = "visual_search"

        payload = {
            "from": "+256700000001",
            "images": [
                {"id": "m1", "caption": ""},
                {"id": "m2", "caption": ""},
                {"id": "m3", "caption": ""},
            ],
            "text": "",
        }

        with (
            patch("src.workers.nlu_router.execute_intent_searches", new_callable=AsyncMock) as mock_exec,
            patch("src.workers.nlu_router.compose_multi_intent_reply", new_callable=AsyncMock, return_value="Results") as mock_comp,
        ):
            await process_batch(payload)

        mock_exec.assert_awaited_once()
        intents = mock_exec.call_args[0][0]
        assert len(intents) == 3
        assert all(i.type == "visual_search" for i in intents)

    @patch("src.workers.nlu_router.extract_nlu")
    @patch("src.workers.nlu_router.download_media")
    async def test_images_with_text_search(self, mock_dl, mock_extract):
        mock_dl.return_value = b"img_bytes"
        mock_extract.return_value = AsyncMock()
        mock_extract.return_value.search_intents = [
            SearchIntent(type="product_search", entities={"product_name": "shoes"}, description="shoes under 100k"),
        ]

        payload = {
            "from": "+256700000001",
            "images": [{"id": "m1", "caption": "nike"}],
            "text": "shoes under 100k",
        }

        with (
            patch("src.workers.nlu_router.execute_intent_searches", new_callable=AsyncMock) as mock_exec,
            patch("src.workers.nlu_router.compose_multi_intent_reply", new_callable=AsyncMock, return_value="Combined") as mock_comp,
        ):
            await process_batch(payload)

        mock_exec.assert_awaited_once()
        intents = mock_exec.call_args[0][0]
        types = [i.type for i in intents]
        assert types == ["visual_search", "product_search"]

    @patch("src.workers.nlu_router.extract_nlu")
    @patch("src.workers.nlu_router.download_media")
    async def test_help_intent_returns_help_text(self, mock_dl, mock_extract):
        mock_extract.return_value = AsyncMock()
        mock_extract.return_value.search_intents = [
            SearchIntent(type="help"),
        ]

        payload = {
            "from": "+256700000001",
            "images": [],
            "text": "help",
        }

        reply = await process_batch(payload)
        assert "Here's what I can do" in reply

    @patch("src.workers.nlu_router.extract_nlu")
    @patch("src.workers.nlu_router.download_media")
    async def test_greeting_no_images_returns_greeting(self, mock_dl, mock_extract):
        mock_extract.return_value = AsyncMock()
        mock_extract.return_value.search_intents = [
            SearchIntent(type="greeting"),
        ]

        payload = {
            "from": "+256700000001",
            "images": [],
            "text": "hello",
        }

        reply = await process_batch(payload)
        assert "Hello! Welcome" in reply

    @patch("src.workers.nlu_router.extract_nlu")
    @patch("src.workers.nlu_router.download_media")
    async def test_no_searchable_intents(self, mock_dl, mock_extract):
        mock_dl.return_value = b"img_bytes"
        mock_extract.return_value = AsyncMock()
        mock_extract.return_value.search_intents = []

        payload = {
            "from": "+256700000001",
            "images": [{"id": "m1", "caption": ""}],
            "text": "",
        }

        with (
            patch("src.workers.nlu_router.execute_intent_searches", new_callable=AsyncMock) as mock_exec,
            patch("src.workers.nlu_router.compose_multi_intent_reply", new_callable=AsyncMock) as mock_comp,
        ):
            await process_batch(payload)

        mock_exec.assert_awaited_once()
        # Even with no NLU intents, image generates a visual_search

    @patch("src.workers.nlu_router.extract_nlu", new_callable=AsyncMock)
    @patch("src.workers.nlu_router.download_media")
    async def test_no_images_no_text(self, mock_dl, mock_extract):
        mock_extract.return_value = AsyncMock()
        mock_extract.return_value.search_intents = []

        payload = {"from": "+256700000001", "images": [], "text": ""}
        with (
            patch(
                "src.workers.nlu_router.compose_no_match_reply",
                new_callable=AsyncMock,
                return_value="Sorry, I couldn't find matching products.",
            ) as mock_no_match,
        ):
            reply = await process_batch(payload)
        assert reply == "Sorry, I couldn't find matching products."
        mock_no_match.assert_awaited_once()

    @patch("src.workers.nlu_router.extract_nlu")
    @patch("src.workers.nlu_router.download_media")
    async def test_greeting_with_images_ignores_greeting(self, mock_dl, mock_extract):
        mock_dl.return_value = b"img"
        mock_extract.return_value = AsyncMock()
        mock_extract.return_value.search_intents = [
            SearchIntent(type="greeting"),
        ]

        payload = {
            "from": "+256700000001",
            "images": [{"id": "m1", "caption": ""}],
            "text": "hello",
        }

        with (
            patch("src.workers.nlu_router.execute_intent_searches", new_callable=AsyncMock) as mock_exec,
            patch("src.workers.nlu_router.compose_multi_intent_reply", new_callable=AsyncMock, return_value="Searched") as mock_comp,
        ):
            reply = await process_batch(payload)

        # With images, greeting should not short-circuit
        assert reply == "Searched"
        mock_exec.assert_awaited_once()

    @patch("src.workers.nlu_router.extract_nlu")
    @patch("src.workers.nlu_router.download_media")
    async def test_images_downloaded_in_parallel(self, mock_dl, mock_extract):
        mock_extract.return_value = AsyncMock()
        mock_extract.return_value.search_intents = []

        payload = {
            "from": "+256700000001",
            "images": [
                {"id": "m1", "caption": ""},
                {"id": "m2", "caption": ""},
            ],
            "text": "",
        }

        with (
            patch("src.workers.nlu_router.execute_intent_searches", new_callable=AsyncMock) as mock_exec,
            patch("src.workers.nlu_router.compose_multi_intent_reply", new_callable=AsyncMock, return_value="ok"),
        ):
            await process_batch(payload)

        # Both images downloaded
        assert mock_dl.await_count == 2
        assert mock_dl.call_args_list[0][0][0] == "m1"
        assert mock_dl.call_args_list[1][0][0] == "m2"
