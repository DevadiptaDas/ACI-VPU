"""test_redact - secret redaction (Phase 2 / E3)."""
import unittest
from aci import redact


class TestRedactText(unittest.TestCase):
    def test_masks_known_secrets(self):
        for text, label in [
            ("my key is sk-ABCDEFGHIJKLMNOPQRSTUVWX done", "openai-key"),
            ("password = hunter2swordfish", "credential-assign"),
            ("api_key: 9f8e7d6c5b4a3210ffff", "credential-assign"),
            ("card 4111 1111 1111 1111 ok", "card"),
            ("ssn 123-45-6789 here", "ssn"),
            ("token eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0."
             "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c here", "jwt"),
        ]:
            out, n = redact.redact_text(text)
            self.assertGreaterEqual(n, 1, text)
            self.assertIn("[REDACTED:" + label + "]", out, text)

    def test_leaves_normal_text(self):
        out, n = redact.redact_text("The quarterly review is scheduled for next Tuesday.")
        self.assertEqual(n, 0)
        self.assertNotIn("REDACTED", out)


class TestProbablySecret(unittest.TestCase):
    def test_bare_credential_detected(self):
        self.assertTrue(redact.is_probably_secret("Xy9$kL2mNp4qVzR7"))   # generated pw
        self.assertTrue(redact.is_probably_secret("aB3#dE6@gH9!jK2&"))

    def test_normal_strings_not_flagged(self):
        self.assertFalse(redact.is_probably_secret("the meeting is at noon"))  # has spaces
        self.assertFalse(redact.is_probably_secret("hello"))                   # too short
        self.assertFalse(redact.is_probably_secret("apple"))                   # low diversity


class TestSensitiveWindow(unittest.TestCase):
    def test_password_managers_and_logins(self):
        self.assertTrue(redact.is_sensitive_window("KeePass", "KeePass.exe"))
        self.assertTrue(redact.is_sensitive_window("Sign in - Bank", "chrome.exe"))
        self.assertTrue(redact.is_sensitive_window("1Password", "1password.exe"))

    def test_normal_windows_ok(self):
        self.assertFalse(redact.is_sensitive_window("report.docx - Word", "winword.exe"))
        self.assertFalse(redact.is_sensitive_window("Inbox", "outlook.exe"))


if __name__ == "__main__":
    unittest.main()
