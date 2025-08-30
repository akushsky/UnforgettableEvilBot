import os
import signal
import subprocess
from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock, patch

from app.whatsapp.service import WhatsAppService


class TestWhatsAppService:
    def setup_method(self):
        self.service = WhatsAppService("/test/session/path", "http://localhost:3000")

    def test_initialization(self):
        """Test service initialization"""
        assert self.service.session_path == "/test/session/path"
        assert self.service.bridge_url == "http://localhost:3000"
        assert self.service.bridge_process is None
        assert self.service.is_connected is False
        assert self.service.http_client is not None

    @patch("app.whatsapp.service.subprocess.Popen")
    @patch("app.whatsapp.service.os.path.join")
    @patch("app.whatsapp.service.os.path.dirname")
    @patch("app.whatsapp.service.os.name")
    async def test_start_bridge_if_needed_bridge_running(
        self, mock_os_name, mock_dirname, mock_join, mock_popen
    ):
        """Test starting bridge when bridge is already running"""
        # Mock successful health check
        mock_response = Mock()
        mock_response.status_code = 200
        self.service.http_client.get = AsyncMock(return_value=mock_response)

        result = await self.service.start_bridge_if_needed()

        assert result
        self.service.http_client.get.assert_called_once_with(
            f"{self.service.bridge_url}/health", timeout=2.0
        )
        mock_popen.assert_not_called()

    @patch("app.whatsapp.service.subprocess.Popen")
    @patch("app.whatsapp.service.os.path.join")
    @patch("app.whatsapp.service.os.path.dirname")
    @patch("app.whatsapp.service.os.name")
    @patch("app.whatsapp.service.os.setsid")
    async def test_start_bridge_if_needed_start_bridge(
        self, mock_setsid, mock_os_name, mock_dirname, mock_join, mock_popen
    ):
        """Test starting bridge when bridge is not running"""
        # Mock failed health check initially, then successful
        mock_response = Mock()
        mock_response.status_code = 200

        self.service.http_client.get = AsyncMock()
        self.service.http_client.get.side_effect = [
            Exception("Connection failed"),  # First call fails
            mock_response,  # Second call succeeds
        ]

        mock_process = Mock()
        mock_popen.return_value = mock_process
        mock_join.return_value = "/test/bridge/path"
        mock_os_name.return_value = "posix"

        result = await self.service.start_bridge_if_needed()

        assert result
        assert self.service.bridge_process == mock_process
        mock_popen.assert_called_once_with(
            ["node", "bridge.js"],
            cwd="/test/bridge/path",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            preexec_fn=os.setsid,
        )

    @patch("app.whatsapp.service.subprocess.Popen")
    @patch("app.whatsapp.service.os.path.join")
    @patch("app.whatsapp.service.os.path.dirname")
    @patch("app.whatsapp.service.os.name")
    async def test_start_bridge_if_needed_failure(
        self, mock_os_name, mock_dirname, mock_join, mock_popen
    ):
        """Test bridge startup failure"""
        # Mock failed health check
        self.service.http_client.get = AsyncMock(
            side_effect=Exception("Connection failed")
        )

        mock_process = Mock()
        mock_popen.return_value = mock_process
        mock_join.return_value = "/test/bridge/path"
        mock_os_name.return_value = "posix"

        result = await self.service.start_bridge_if_needed()

        assert result is False
        mock_popen.assert_called_once()

    @patch.object(WhatsAppService, "start_bridge_if_needed")
    async def test_initialize_client_success(self, mock_start_bridge):
        """Test successful client initialization"""
        mock_start_bridge.return_value = True

        mock_response = Mock()
        mock_response.status_code = 200
        self.service.http_client.post = AsyncMock(return_value=mock_response)

        with patch.object(self.service, "get_client_status"):
            result = await self.service.initialize_client(123)

            assert result
            assert self.service.is_connected
            mock_start_bridge.assert_called_once()
            self.service.http_client.post.assert_called_once_with(
                f"{self.service.bridge_url}/initialize/123", timeout=30.0
            )

    @patch.object(WhatsAppService, "start_bridge_if_needed")
    async def test_initialize_client_bridge_failure(self, mock_start_bridge):
        """Test client initialization when bridge fails to start"""
        mock_start_bridge.return_value = False

        result = await self.service.initialize_client(123)

        assert result is False
        assert self.service.is_connected is False

    @patch.object(WhatsAppService, "start_bridge_if_needed")
    async def test_initialize_client_http_error(self, mock_start_bridge):
        """Test client initialization with HTTP error"""
        mock_start_bridge.return_value = True

        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        self.service.http_client.post = AsyncMock(return_value=mock_response)

        result = await self.service.initialize_client(123)

        assert result is False
        assert self.service.is_connected is False

    @patch.object(WhatsAppService, "start_bridge_if_needed")
    async def test_initialize_client_exception(self, mock_start_bridge):
        """Test client initialization with exception"""
        mock_start_bridge.return_value = True
        self.service.http_client.post = AsyncMock(
            side_effect=Exception("Network error")
        )

        result = await self.service.initialize_client(123)

        assert result is False
        assert self.service.is_connected is False

    async def test_get_client_status_success(self):
        """Test successful client status retrieval"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"connected": True, "status": "ready"}
        self.service.http_client.get = AsyncMock(return_value=mock_response)

        result = await self.service.get_client_status(123)

        assert result == {"connected": True, "status": "ready"}
        self.service.http_client.get.assert_called_once_with(
            f"{self.service.bridge_url}/status/123", timeout=10.0
        )

    async def test_get_client_status_http_error(self):
        """Test client status retrieval with HTTP error"""
        mock_response = Mock()
        mock_response.status_code = 404
        mock_response.text = "Not Found"
        self.service.http_client.get = AsyncMock(return_value=mock_response)

        result = await self.service.get_client_status(123)

        assert result == {"connected": False, "error": "Not Found"}

    async def test_get_client_status_exception(self):
        """Test client status retrieval with exception"""
        self.service.http_client.get = AsyncMock(side_effect=Exception("Network error"))

        result = await self.service.get_client_status(123)

        assert result == {"connected": False, "error": "Network error"}

    async def test_get_chats_success(self):
        """Test successful chat retrieval"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "chats": [
                {"id": "chat1", "name": "Chat 1"},
                {"id": "chat2", "name": "Chat 2"},
            ]
        }
        self.service.http_client.get = AsyncMock(return_value=mock_response)

        result = await self.service.get_chats(123)

        assert result == [
            {"id": "chat1", "name": "Chat 1"},
            {"id": "chat2", "name": "Chat 2"},
        ]
        self.service.http_client.get.assert_called_once_with(
            f"{self.service.bridge_url}/chats/123", timeout=30.0
        )

    async def test_get_chats_http_error(self):
        """Test chat retrieval with HTTP error"""
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        self.service.http_client.get = AsyncMock(return_value=mock_response)

        result = await self.service.get_chats(123)

        assert result == []

    async def test_get_chats_exception(self):
        """Test chat retrieval with exception"""
        self.service.http_client.get = AsyncMock(side_effect=Exception("Network error"))

        result = await self.service.get_chats(123)

        assert result == []

    async def test_get_new_messages_success(self):
        """Test successful message retrieval"""
        since = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        chat_ids = ["chat1", "chat2"]

        # Mock responses for each chat
        mock_response1 = Mock()
        mock_response1.status_code = 200
        mock_response1.json.return_value = {
            "messages": [
                {
                    "timestamp": "2024-01-01T13:00:00Z",
                    "fromMe": False,
                    "text": "Message 1",
                },
                {
                    "timestamp": "2024-01-01T14:00:00Z",
                    "fromMe": True,  # Should be filtered out
                    "text": "Message 2",
                },
            ]
        }

        mock_response2 = Mock()
        mock_response2.status_code = 200
        mock_response2.json.return_value = {
            "messages": [
                {
                    "timestamp": "2024-01-01T15:00:00Z",
                    "fromMe": False,
                    "text": "Message 3",
                }
            ]
        }

        self.service.http_client.get = AsyncMock()
        self.service.http_client.get.side_effect = [mock_response1, mock_response2]

        result = await self.service.get_new_messages(123, chat_ids, since)

        assert len(result) == 2
        assert result[0]["text"] == "Message 1"
        assert result[0]["chat_id"] == "chat1"
        assert result[1]["text"] == "Message 3"
        assert result[1]["chat_id"] == "chat2"

        # Verify calls
        # expected_calls = [  # Unused variable
        #     (
        #         (f"{self.service.bridge_url}/messages/123/chat1",),
        #         {"params": {"limit": 100, "since": since.isoformat()}, "timeout": 30.0},
        #     ),
        #     (
        #         (f"{self.service.bridge_url}/messages/123/chat2",),
        #         {"params": {"limit": 100, "since": since.isoformat()}, "timeout": 30.0},
        #     ),
        # ]
        assert self.service.http_client.get.call_count == 2

    async def test_get_new_messages_http_error(self):
        """Test message retrieval with HTTP error"""
        since = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        chat_ids = ["chat1"]

        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        self.service.http_client.get = AsyncMock(return_value=mock_response)

        result = await self.service.get_new_messages(123, chat_ids, since)

        assert result == []

    async def test_get_new_messages_exception(self):
        """Test message retrieval with exception"""
        since = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        chat_ids = ["chat1"]

        self.service.http_client.get = AsyncMock(side_effect=Exception("Network error"))

        result = await self.service.get_new_messages(123, chat_ids, since)

        assert result == []

    async def test_get_new_messages_filter_by_time(self):
        """Test message filtering by time"""
        since = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        chat_ids = ["chat1"]

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "messages": [
                {
                    "timestamp": "2024-01-01T11:00:00Z",  # Before since time
                    "fromMe": False,
                    "text": "Old Message",
                },
                {
                    "timestamp": "2024-01-01T13:00:00Z",  # After since time
                    "fromMe": False,
                    "text": "New Message",
                },
            ]
        }

        self.service.http_client.get = AsyncMock(return_value=mock_response)

        result = await self.service.get_new_messages(123, chat_ids, since)

        assert len(result) == 1
        assert result[0]["text"] == "New Message"

    async def test_disconnect_success(self):
        """Test successful disconnection"""
        mock_response = Mock()
        mock_response.status_code = 200
        self.service.http_client.post = AsyncMock(return_value=mock_response)
        self.service.is_connected = True

        await self.service.disconnect(123)

        assert self.service.is_connected is False
        self.service.http_client.post.assert_called_once_with(
            f"{self.service.bridge_url}/disconnect/123", timeout=10.0
        )

    async def test_disconnect_http_error(self):
        """Test disconnection with HTTP error"""
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        self.service.http_client.post = AsyncMock(return_value=mock_response)
        self.service.is_connected = True

        await self.service.disconnect(123)

        # Should still be connected since disconnection failed
        assert self.service.is_connected

    async def test_disconnect_exception(self):
        """Test disconnection with exception"""
        self.service.http_client.post = AsyncMock(
            side_effect=Exception("Network error")
        )
        self.service.is_connected = True

        await self.service.disconnect(123)

        # Should still be connected since disconnection failed
        assert self.service.is_connected

    @patch("app.whatsapp.service.os.name")
    @patch("app.whatsapp.service.os.killpg")
    @patch("app.whatsapp.service.os.getpgid")
    def test_del_cleanup_posix(self, mock_getpgid, mock_killpg, mock_os_name):
        """Test cleanup on POSIX systems"""
        mock_os_name.return_value = "posix"
        mock_process = Mock()
        mock_process.pid = 12345
        self.service.bridge_process = mock_process
        mock_getpgid.return_value = 12345

        # Trigger cleanup
        self.service.__del__()

        mock_getpgid.assert_called_once_with(12345)
        mock_killpg.assert_called_once_with(12345, signal.SIGTERM)

    @patch("app.whatsapp.service.os.name", "nt")
    def test_del_cleanup_windows(self):
        """Test cleanup on Windows systems"""
        mock_process = Mock()
        self.service.bridge_process = mock_process

        # Trigger cleanup
        self.service.__del__()

        # The cleanup should call terminate on the process
        mock_process.terminate.assert_called_once()

    @patch("app.whatsapp.service.os.name")
    @patch("app.whatsapp.service.os.killpg")
    def test_del_cleanup_exception(self, mock_killpg, mock_os_name):
        """Test cleanup with exception handling"""
        mock_os_name.return_value = "posix"
        mock_process = Mock()
        mock_process.pid = 12345
        self.service.bridge_process = mock_process
        mock_killpg.side_effect = Exception("Process not found")

        # Should not raise exception
        self.service.__del__()

    def test_del_no_process(self):
        """Test cleanup when no process exists"""
        self.service.bridge_process = None

        # Should not raise exception
        self.service.__del__()

    async def test_get_new_messages_empty_chat_ids(self):
        """Test message retrieval with empty chat IDs"""
        since = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        chat_ids: list[str] = []

        result = await self.service.get_new_messages(123, chat_ids, since)

        assert result == []
        # Since chat_ids is empty, no HTTP calls should be made
        # We can't easily test this without mocking the method, so we just verify
        # the result

    async def test_get_new_messages_mixed_responses(self):
        """Test message retrieval with mixed success/failure responses"""
        since = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        chat_ids = ["chat1", "chat2"]

        # First chat succeeds, second fails
        mock_response1 = Mock()
        mock_response1.status_code = 200
        mock_response1.json.return_value = {
            "messages": [
                {
                    "timestamp": "2024-01-01T13:00:00Z",
                    "fromMe": False,
                    "text": "Message 1",
                }
            ]
        }

        mock_response2 = Mock()
        mock_response2.status_code = 500
        mock_response2.text = "Internal Server Error"

        self.service.http_client.get = AsyncMock()
        self.service.http_client.get.side_effect = [mock_response1, mock_response2]

        result = await self.service.get_new_messages(123, chat_ids, since)

        assert len(result) == 1
        assert result[0]["text"] == "Message 1"
        assert result[0]["chat_id"] == "chat1"
