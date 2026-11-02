"""Persistent auth token mint / verify + logout guard."""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import MagicMock, patch


class AuthSessionTokenTest(unittest.TestCase):
    def setUp(self):
        os.environ["AUTH_SESSION_SECRET"] = "unit-test-secret"
        os.environ["AUTH_SESSION_DAYS"] = "30"

    def test_mint_and_verify_roundtrip(self):
        import auth_utils as au

        tok = au.mint_auth_token("admin", "ops@example.com", "whitelist", now=1_700_000_000)
        parsed = au.verify_auth_token(tok, now=1_700_000_000 + 60)
        self.assertIsNotNone(parsed)
        role, identity, via, exp = parsed
        self.assertEqual(role, "admin")
        self.assertEqual(identity, "ops@example.com")
        self.assertEqual(via, "whitelist")
        self.assertGreater(exp, 1_700_000_000)

    def test_expired_token_rejected(self):
        import auth_utils as au

        tok = au.mint_auth_token(
            "user", "u1", "whitelist", ttl_days=1, now=1_700_000_000
        )
        self.assertIsNone(
            au.verify_auth_token(tok, now=1_700_000_000 + 2 * 86400)
        )

    def test_tampered_token_rejected(self):
        import auth_utils as au

        tok = au.mint_auth_token("admin", "a", "whitelist", now=1_700_000_000)
        bad = tok[:-4] + ("AAAA" if not tok.endswith("AAAA") else "BBBB")
        self.assertIsNone(au.verify_auth_token(bad, now=1_700_000_000 + 10))

    def test_secret_rotation_invalidates_old(self):
        import auth_utils as au

        tok = au.mint_auth_token("admin", "a", "whitelist", now=1_700_000_000)
        with patch.dict(os.environ, {"AUTH_SESSION_SECRET": "other-secret"}):
            self.assertIsNone(au.verify_auth_token(tok, now=1_700_000_000 + 10))

    def test_logout_guard_blocks_query_token_restore(self):
        """登出後即使 URL 仍有 j18_auth，也不應自動還原。"""
        import auth_utils as au

        tok = au.mint_auth_token(
            "admin", "ops@example.com", "whitelist", now=1_700_000_000
        )
        ss = {au.SESSION_LOGOUT_GUARD: True}
        qp = {au.AUTH_QUERY_PARAM: tok}

        fake_st = MagicMock()
        fake_st.session_state = ss
        fake_st.query_params = qp

        with patch.dict(sys.modules, {"streamlit": fake_st}):
            with patch.object(au, "inject_auth_browser_store") as inj:
                au.try_restore_auth_from_browser()
                inj.assert_called()
                self.assertTrue(inj.call_args.kwargs.get("clear"))

        self.assertNotIn(au.SESSION_ROLE, ss)
        self.assertNotIn(au.AUTH_QUERY_PARAM, qp)

    def test_logout_sets_guard(self):
        import auth_utils as au

        ss = {
            au.SESSION_ROLE: "admin",
            au.SESSION_IDENTITY: "ops@example.com",
            au.SESSION_VIA: "whitelist",
            au.SESSION_TOKEN: "tok",
        }
        fake_st = MagicMock()
        fake_st.session_state = ss
        fake_st.query_params = {}

        with patch.dict(sys.modules, {"streamlit": fake_st}):
            with patch.object(au, "inject_auth_browser_store") as inj:
                au.logout()
                inj.assert_called_with(clear=True)

        self.assertTrue(ss.get(au.SESSION_LOGOUT_GUARD))
        self.assertNotIn(au.SESSION_ROLE, ss)
        self.assertNotIn(au.SESSION_TOKEN, ss)


if __name__ == "__main__":
    unittest.main()
