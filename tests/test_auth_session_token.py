"""Persistent auth token mint / verify."""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch


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
            # re-import secret reader path uses env each call
            self.assertIsNone(au.verify_auth_token(tok, now=1_700_000_000 + 10))


if __name__ == "__main__":
    unittest.main()
