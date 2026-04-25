from unittest.mock import MagicMock, patch

import requests

from src.body_client import BodyClient


class TestGetStatus:
    def test_happy_path(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "ok": True,
            "bot": {
                "username": "Builder",
                "health": 20,
                "position": {"x": 0, "y": 64, "z": 0},
            },
        }
        mock_response.raise_for_status.return_value = None

        with patch(
            "src.body_client.requests.get", return_value=mock_response
        ) as mock_get:
            client = BodyClient()
            result = client.get_status()

        mock_get.assert_called_once_with("http://127.0.0.1:3000/status", timeout=5)
        assert result["ok"] is True
        assert result["bot"]["username"] == "Builder"
        assert result["bot"]["health"] == 20

    def test_bot_disconnected(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"ok": True, "bot": None}
        mock_response.raise_for_status.return_value = None

        with patch("src.body_client.requests.get", return_value=mock_response):
            result = BodyClient().get_status()

        assert result["ok"] is True
        assert result["bot"] is None

    def test_connection_refused(self):
        with patch(
            "src.body_client.requests.get",
            side_effect=requests.ConnectionError("Connection refused"),
        ):
            try:
                BodyClient().get_status()
                assert False, "Should have raised ConnectionError"
            except requests.ConnectionError:
                pass

    def test_timeout(self):
        with patch(
            "src.body_client.requests.get",
            side_effect=requests.Timeout("Request timed out"),
        ):
            try:
                BodyClient().get_status()
                assert False, "Should have raised Timeout"
            except requests.Timeout:
                pass


class TestClientConfig:
    def test_default_url(self):
        client = BodyClient()
        assert client.base_url == "http://127.0.0.1:3000"

    def test_env_var_url(self, monkeypatch):
        monkeypatch.setenv("BOT_URL", "http://192.168.1.100:4000")
        client = BodyClient()
        assert client.base_url == "http://192.168.1.100:4000"

    def test_custom_url_via_constructor(self):
        client = BodyClient(base_url="http://custom:9999")
        assert client.base_url == "http://custom:9999"

    def test_constructor_overrides_env(self, monkeypatch):
        monkeypatch.setenv("BOT_URL", "http://from-env:4000")
        client = BodyClient(base_url="http://from-constructor:9999")
        assert client.base_url == "http://from-constructor:9999"


class TestExecute:
    def _make_mock_response(self, json_data):
        mock_response = MagicMock()
        mock_response.json.return_value = json_data
        mock_response.raise_for_status.return_value = None
        return mock_response

    def test_execute_happy_path(self):
        envelope = {
            "success": True,
            "data": {"blocks_mined": 1},
            "tool": "mine",
            "duration_ms": 3420,
        }
        mock_response = self._make_mock_response(envelope)

        with patch("src.body_client.requests.post", return_value=mock_response):
            result = BodyClient().execute("mine", {"target": "oak_log"})

        assert result == envelope
        assert result["success"] is True
        assert result["duration_ms"] == 3420

    def test_execute_tool_failure_returned_in_envelope(self):
        envelope = {
            "success": False,
            "error": {"code": "NOT_IMPLEMENTED", "message": "Tool not implemented"},
            "tool": "mine",
            "duration_ms": 10,
        }
        mock_response = self._make_mock_response(envelope)

        with patch("src.body_client.requests.post", return_value=mock_response):
            result = BodyClient().execute("mine", {})

        assert result["success"] is False
        assert result["error"]["code"] == "NOT_IMPLEMENTED"

    def test_execute_invalid_params_raises(self):
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = requests.HTTPError(
            "400 Bad Request"
        )

        with patch("src.body_client.requests.post", return_value=mock_response):
            try:
                BodyClient().execute("mine", None)
                assert False, "Should have raised HTTPError"
            except requests.HTTPError:
                pass

    def test_execute_internal_error_raises(self):
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = requests.HTTPError(
            "500 Internal Server Error"
        )

        with patch("src.body_client.requests.post", return_value=mock_response):
            try:
                BodyClient().execute("mine", {})
                assert False, "Should have raised HTTPError"
            except requests.HTTPError:
                pass

    def test_execute_default_params_empty_dict(self):
        mock_response = self._make_mock_response({"success": True, "tool": "mine"})

        with patch(
            "src.body_client.requests.post", return_value=mock_response
        ) as mock_post:
            BodyClient().execute("mine")

        assert mock_post.call_args.kwargs["json"] == {"tool": "mine", "params": {}}

    def test_execute_explicit_params_passed_through(self):
        mock_response = self._make_mock_response({"success": True, "tool": "mine"})

        with patch(
            "src.body_client.requests.post", return_value=mock_response
        ) as mock_post:
            BodyClient().execute("mine", {"target": "oak_log", "count": 5})

        assert mock_post.call_args.kwargs["json"] == {
            "tool": "mine",
            "params": {"target": "oak_log", "count": 5},
        }

    def test_execute_timeout_is_300s(self):
        mock_response = self._make_mock_response({"success": True, "tool": "mine"})

        with patch(
            "src.body_client.requests.post", return_value=mock_response
        ) as mock_post:
            BodyClient().execute("mine")

        assert mock_post.call_args.kwargs["timeout"] == 300

    def test_execute_posts_to_correct_url(self):
        mock_response = self._make_mock_response({"success": True, "tool": "mine"})

        with patch(
            "src.body_client.requests.post", return_value=mock_response
        ) as mock_post:
            BodyClient().execute("mine")

        assert mock_post.call_args.args[0] == "http://127.0.0.1:3000/execute"

    def test_execute_connection_refused_propagates(self):
        with patch(
            "src.body_client.requests.post",
            side_effect=requests.ConnectionError("Connection refused"),
        ):
            try:
                BodyClient().execute("mine")
                assert False, "Should have raised ConnectionError"
            except requests.ConnectionError:
                pass

    def test_execute_timeout_propagates(self):
        with patch(
            "src.body_client.requests.post",
            side_effect=requests.Timeout("Request timed out"),
        ):
            try:
                BodyClient().execute("mine")
                assert False, "Should have raised Timeout"
            except requests.Timeout:
                pass
