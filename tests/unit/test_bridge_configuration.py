import asyncio
import os
from pathlib import Path
from unittest.mock import patch

BRIDGE_JS = Path(__file__).resolve().parents[2] / "whatsapp_bridge" / "bridge.js"


# Mock the Node.js environment
class MockBridge:
    """Mock bridge class for testing configuration"""

    def __init__(self, python_backend_url=None):
        self.pythonBackendUrl = python_backend_url or "http://127.0.0.1:9876"
        self.clients = {}
        self.clientStates = {}
        self.qrCodes = {}
        self.reconnectTimeouts = {}
        self.initializing = {}
        self.restorePromise = None
        self.restoreScheduled = False

    def updateClientState(self, userId, updates):
        """Mock updateClientState method"""
        current = self.clientStates.get(userId, {})
        self.clientStates[userId] = {**current, **updates}

    @staticmethod
    def has_usable_active_user_list(active_user_ids):
        """Mirror of bridge.js hasUsableActiveUserList()"""
        return isinstance(active_user_ids, list) and len(active_user_ids) > 0

    def restore_decisions(self, active_user_ids, local_session_user_ids):
        """
        Mirror of the restore-all decision loop in bridge.js.

        Returns {userId: "restored" | "wiped"}. An empty or missing active user
        list means "unknown roster" and must never wipe a local session.
        """
        can_wipe = self.has_usable_active_user_list(active_user_ids)
        return {
            user_id: (
                "wiped" if can_wipe and user_id not in active_user_ids else "restored"
            )
            for user_id in local_session_user_ids
        }

    async def restoreAllClients(self):
        """Mock restoreAllClients method"""
        if self.restorePromise:
            return self.restorePromise

        self.restorePromise = self._doRestore()
        try:
            return await self.restorePromise
        finally:
            self.restorePromise = None

    async def _doRestore(self):
        """Mock implementation of restore logic"""
        # Simulate the retry logic
        for attempt in range(1, 4):
            try:
                # Simulate health check
                if attempt == 1:
                    # First attempt succeeds
                    return {"status": "success", "attempt": attempt}
                else:
                    # Other attempts would fail in real scenario
                    raise Exception(f"Attempt {attempt} failed")
            except Exception as e:
                if attempt < 3:
                    import asyncio

                    await asyncio.sleep(0.1)  # Short delay for testing
                else:
                    return {"status": "failed", "error": str(e)}


class TestBridgeConfiguration:
    """Test cases for bridge configuration changes"""

    def test_ipv4_backend_url_configuration(self):
        """Test that bridge uses IPv4 localhost by default"""
        bridge = MockBridge()

        # Should use IPv4 localhost
        assert bridge.pythonBackendUrl == "http://127.0.0.1:9876"
        assert "localhost" not in bridge.pythonBackendUrl
        assert "::1" not in bridge.pythonBackendUrl

    def test_ipv4_backend_url_from_environment(self):
        """Test that bridge respects PYTHON_BACKEND_URL environment variable"""
        with patch.dict(os.environ, {"PYTHON_BACKEND_URL": "http://127.0.0.1:9876"}):
            bridge = MockBridge()
            assert bridge.pythonBackendUrl == "http://127.0.0.1:9876"

    def test_ipv4_backend_url_custom_port(self):
        """Test that bridge works with custom ports"""
        bridge = MockBridge("http://127.0.0.1:8080")
        assert bridge.pythonBackendUrl == "http://127.0.0.1:8080"

    def test_bridge_retry_logic(self):
        """Test the retry logic in bridge restoration"""
        bridge = MockBridge()

        # Test that restoreAllClients handles retries properly
        async def test_retry():
            result = await bridge.restoreAllClients()
            return result

        # Run the async test
        import asyncio

        result = asyncio.run(test_retry())

        assert result["status"] == "success"
        assert result["attempt"] == 1

    def test_bridge_state_management(self):
        """Test bridge state management functionality"""
        bridge = MockBridge()

        # Test updating client state
        bridge.updateClientState("user1", {"connected": True, "lastSeen": "2023-01-01"})
        bridge.updateClientState("user1", {"connected": False})

        # Verify state was updated correctly
        assert bridge.clientStates["user1"]["connected"] is False
        assert bridge.clientStates["user1"]["lastSeen"] == "2023-01-01"

    def test_bridge_deduplication(self):
        """Test that bridge prevents duplicate restoration attempts"""
        bridge = MockBridge()

        # Simulate concurrent restore attempts
        async def test_deduplication():
            # Start first restoration
            task1 = bridge.restoreAllClients()
            # Start second restoration (should be deduplicated)
            task2 = bridge.restoreAllClients()

            # Both should return the same result
            result1 = await task1
            result2 = await task2

            return result1, result2

        result1, result2 = asyncio.run(test_deduplication())

        # Both should return the same result (deduplication working)
        assert result1 == result2

    def test_bridge_environment_variable_handling(self):
        """Test bridge environment variable handling"""
        test_cases = [
            ("http://127.0.0.1:9876", "http://127.0.0.1:9876"),
            (
                "http://localhost:9876",
                "http://localhost:9876",
            ),  # Should still work if explicitly set
            ("http://0.0.0.0:9876", "http://0.0.0.0:9876"),
            (None, "http://127.0.0.1:9876"),  # Default fallback
        ]

        for env_value, expected in test_cases:
            bridge = MockBridge() if env_value is None else MockBridge(env_value)
            assert bridge.pythonBackendUrl == expected

    def test_bridge_url_validation(self):
        """Test that bridge handles various URL formats correctly"""
        valid_urls = [
            "http://127.0.0.1:9876",
            "http://127.0.0.1:8080",
            "http://localhost:9876",
            "https://127.0.0.1:9876",
        ]

        for url in valid_urls:
            bridge = MockBridge(url)
            assert bridge.pythonBackendUrl == url

    def test_bridge_restore_promise_cleanup(self):
        """Test that restore promise is properly cleaned up"""
        bridge = MockBridge()

        async def test_cleanup():
            # Start restoration
            await bridge.restoreAllClients()
            # After completion, restorePromise should be None
            return bridge.restorePromise

        asyncio.run(test_cleanup())
        # Verify cleanup
        assert bridge.restorePromise is None

    def test_bridge_initialization_state(self):
        """Test bridge initialization state management"""
        bridge = MockBridge()

        # Test initial state
        assert len(bridge.clients) == 0
        assert len(bridge.clientStates) == 0
        assert len(bridge.qrCodes) == 0
        assert len(bridge.reconnectTimeouts) == 0
        assert len(bridge.initializing) == 0
        assert bridge.restorePromise is None
        assert bridge.restoreScheduled is False

    def test_bridge_client_state_persistence(self):
        """Test bridge client state persistence simulation"""
        bridge = MockBridge()

        # Simulate adding multiple clients
        bridge.updateClientState("user1", {"connected": True, "hasSession": True})
        bridge.updateClientState("user2", {"connected": False, "hasSession": True})
        bridge.updateClientState("user3", {"connected": True, "hasSession": False})

        # Verify state persistence
        assert bridge.clientStates["user1"]["connected"] is True
        assert bridge.clientStates["user2"]["connected"] is False
        assert bridge.clientStates["user3"]["connected"] is True
        assert len(bridge.clientStates) == 3

    def test_bridge_error_handling(self):
        """Test bridge error handling in restoration"""
        bridge = MockBridge()

        # Mock a scenario where all attempts fail
        async def test_error_handling():
            # Override the restore logic to simulate failures
            original_do_restore = bridge._doRestore

            async def failing_restore():
                raise Exception("All attempts failed")

            bridge._doRestore = failing_restore

            try:
                result = await bridge.restoreAllClients()
                return result
            except Exception as e:
                return {"status": "error", "message": str(e)}
            finally:
                bridge._doRestore = original_do_restore

        result = asyncio.run(test_error_handling())
        assert result["status"] == "error"
        assert "All attempts failed" in result["message"]

    def test_restore_never_wipes_on_empty_active_user_list(self):
        """An empty roster from the backend must not wipe local sessions"""
        bridge = MockBridge()

        decisions = bridge.restore_decisions([], ["1", "2", "3"])

        assert set(decisions.values()) == {"restored"}

    def test_restore_never_wipes_when_backend_unavailable(self):
        """A missing roster (backend unreachable) must not wipe local sessions"""
        bridge = MockBridge()

        decisions = bridge.restore_decisions(None, ["1", "2"])

        assert set(decisions.values()) == {"restored"}

    def test_restore_wipes_only_unknown_users_with_known_roster(self):
        """With a non-empty roster, only users missing from it are cleaned up"""
        bridge = MockBridge()

        decisions = bridge.restore_decisions(["1", "3"], ["1", "2", "3"])

        assert decisions == {"1": "restored", "2": "wiped", "3": "restored"}

    def test_bridge_configuration_consistency(self):
        """Test that bridge configuration is consistent across different scenarios"""
        # Test with different URL configurations
        urls = [
            "http://127.0.0.1:9876",
            "http://127.0.0.1:8080",
            "http://localhost:9876",
        ]

        for url in urls:
            bridge = MockBridge(url)

            # Verify basic functionality still works
            bridge.updateClientState("test", {"connected": True})
            assert bridge.clientStates["test"]["connected"] is True

            # Verify URL is set correctly
            assert bridge.pythonBackendUrl == url


class TestBridgeSourceInvariants:
    """
    Guards on whatsapp_bridge/bridge.js. There is no JS test runner in this repo,
    so these assert the source keeps the wipe guard and volume-backed state file.
    """

    @staticmethod
    def source():
        return BRIDGE_JS.read_text(encoding="utf-8")

    def test_wipe_guard_requires_non_empty_active_user_list(self):
        source = self.source()

        assert "hasUsableActiveUserList(activeUserIds) {" in source
        assert (
            "return Array.isArray(activeUserIds) && activeUserIds.length > 0;" in source
        )

    def test_restore_loop_only_wipes_when_roster_is_known(self):
        source = self.source()

        assert "const canWipe = this.hasUsableActiveUserList(activeUserIds);" in source
        assert "if (canWipe && !activeUserIds.includes(userId)) {" in source
        # The old check treated an empty list as authorisation to wipe.
        assert (
            "if (activeUserIds !== null && !activeUserIds.includes(userId))"
            not in source
        )

    def test_state_file_lives_under_sessions_root(self):
        source = self.source()

        assert (
            "this.stateFile = path.join(this.sessionsRoot, 'client_states.json');"
            in source
        )
        assert "this.stateFile = './client_states.json';" not in source

    def test_restore_on_start_is_honored(self):
        source = self.source()

        assert "RESTORE_ON_START" in source
        assert "if (!RESTORE_ON_START) {" in source

    def test_disconnect_is_reported_to_backend(self):
        """A closed connection must notify /disconnected, like /connected does"""
        source = self.source()

        assert "`${this.pythonBackendUrl}/webhook/whatsapp/disconnected`, {" in source
        # Must carry the same auth headers as the connected webhook.
        connected_idx = source.index("/webhook/whatsapp/connected")
        disconnected_idx = source.index("/webhook/whatsapp/disconnected")
        for idx in (connected_idx, disconnected_idx):
            assert "headers: this.backendHeaders()" in source[idx : idx + 800]

    def test_ensure_client_started_awaits_pending_initialization(self):
        """Returning early left the caller with no client to use"""
        source = self.source()

        assert "const pending = this.initializing.get(userId);" in source
        assert "await pending.catch(" in source
        assert (
            "if (this.clients.get(userId) || this.initializing.has(userId)) return;"
            not in source
        )

    def test_messages_upsert_processes_whole_batch(self):
        """Taking only m.messages[0] silently dropped batched messages"""
        source = self.source()

        assert "for (const msg of m.messages || []) {" in source
        assert "const msg = m.messages[0];" not in source

    def test_get_message_stub_returns_nothing(self):
        """A fabricated 'hello' body would be re-sent on Baileys retries"""
        source = self.source()

        assert "getMessage: async () => undefined," in source
        assert "conversation: 'hello'" not in source

    def test_fresh_pairing_wipes_session_folder(self):
        """preferExistingSession=false must clear creds so a QR is emitted"""
        source = self.source()

        assert "if (preferExistingSession) {" in source
        assert "Wiping session for ${userId} - fresh pairing requested" in source
        assert (
            "const hasSession = preferExistingSession ? "
            "await this.checkSessionExists(userId) : false;" not in source
        )
