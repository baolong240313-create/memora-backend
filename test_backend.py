import os
import sys
import tempfile
import unittest

# Use an isolated temp DB so tests don't touch real user data.
os.environ["MEMORA_DB"] = os.path.join(tempfile.mkdtemp(), "test_memora.db")

# Make sure the project dir is importable regardless of where the test runs.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import generator
import db
import app

class TestBackend(unittest.TestCase):
    def test_heuristic_qa(self):
        sample = """
        Q: What is Photosynthesis?
        A: The biological process by which plants convert light energy into chemical energy.

        Question 2: What is ATP?
        Answer 2: The primary energy carrier in all living organisms.
        """
        cards = generator.generate(sample, "Biology", "Medium", 5, "q&a")
        self.assertEqual(len(cards), 2)
        self.assertIn("Photosynthesis", cards[0]["front"])

    def test_no_junk_cards_from_leftover_lines(self):
        # Regression: structured Q/A lines must NOT be re-parsed into junk cards
        sample = """
        Q: What is Photosynthesis?
        A: The biological process by which plants convert light energy into chemical energy.
        Question 2: What is ATP?
        Answer 2: The primary energy carrier in all living organisms.
        """
        cards = generator.generate(sample, "Biology", "Medium", 5, "q&a")
        fronts = [c["front"].lower() for c in cards]
        for junk in ["what is question 2", "what is answer 2", "key concept"]:
            self.assertNotIn(junk, fronts)
        self.assertEqual(len(cards), 2)

    def test_heuristic_table(self):
        sample = """
        | Term | Definition |
        | --- | --- |
        | Mitochondria | Powerhouse of the cell |
        | Ribosome | Protein synthesis factory |
        """
        cards = generator.generate(sample, "Biology", "Medium", 5, "term")
        self.assertEqual(len(cards), 2)
        self.assertEqual(cards[0]["front"], "Mitochondria")
        self.assertEqual(cards[0]["back"], "Powerhouse of the cell")

    def test_heuristic_bullets(self):
        sample = """
        - **Neuron**: The fundamental cellular unit of the brain and nervous system.
        - **Synapse**: The junction between two nerve cells.
        """
        cards = generator.generate(sample, "Neurology", "Medium", 5, "q&a")
        self.assertEqual(len(cards), 2)
        self.assertIn("Neuron", cards[0]["front"])

    def test_heuristic_prose(self):
        sample = """
        Cellular respiration is the process of breaking down glucose into ATP.
        The cell membrane is responsible for regulating nutrient transport.
        """
        cards = generator.generate(sample, "Biology", "Medium", 5, "q&a")
        self.assertTrue(len(cards) >= 1)

    def test_empty_notes(self):
        cards = generator.generate("", "General", "Medium", 5, "q&a")
        self.assertEqual(cards, [])

    def test_app_client(self):
        client = app.app.test_client()
        resp = client.get("/api/health")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json.get("ok"))

        # Test empty notes 400
        gen_resp = client.post("/api/generate", json={"notes": ""})
        self.assertEqual(gen_resp.status_code, 400)
        self.assertIn("error", gen_resp.json)

        # Test unauthenticated deck 401
        deck_resp = client.get("/api/decks/999999", headers={"Authorization": "Bearer invalid"})
        self.assertEqual(deck_resp.status_code, 401)

    def test_sm2_interval_growth(self):
        uid = db.create_user("srs@test.com", "hash", "SRS")
        did = db.create_deck(uid, "Deck", "Subject")
        cid = db.add_one_card(did, "Front", "Back", "q&a")
        db.update_card_stats(cid, True)  # reps 1 -> interval 1
        db.update_card_stats(cid, True)  # reps 2 -> interval 6
        db.update_card_stats(cid, True)  # reps 3 -> interval ~ round(6*ease)
        with db.get_db() as c:
            row = c.execute(
                "SELECT reps, interval AS i, mastered, ease FROM card_stats WHERE card_id=?",
                (cid,),
            ).fetchone()
        self.assertEqual(row["reps"], 3)
        self.assertGreaterEqual(row["i"], 6)
        self.assertEqual(row["mastered"], 1)

    def test_guest_card_sets_signed_cookie(self):
        client = app.app.test_client()
        r = client.post("/api/generate", json={"notes": "A is a type of B.", "number": 5})
        self.assertEqual(r.status_code, 200)
        cookies = r.headers.getlist("Set-Cookie")
        self.assertTrue(any(c.startswith("memora_guest=") for c in cookies))
        # Second call with the issued cookie is blocked (limit already used).
        gid = next(c.split("=")[1].split(";")[0] for c in cookies if c.startswith("memora_guest="))
        r2 = client.post(
            "/api/generate",
            json={"notes": "C is D.", "number": 5},
            headers={"Cookie": f"memora_guest={gid}"},
        )
        self.assertEqual(r2.status_code, 402)

    def test_password_reset_flow(self):
        import hashlib
        uid = db.create_user("reset@test.com", "hash", "reset")
        code = "123456"
        code_hash = hashlib.sha256(code.encode()).hexdigest()
        db.create_password_reset(uid, code_hash, db._ts() + 300)
        self.assertEqual(db.find_valid_reset(code_hash), uid)
        db.clear_resets_for_user(uid)
        self.assertIsNone(db.find_valid_reset(code_hash))

    def test_changelog_endpoint(self):
        client = app.app.test_client()
        r = client.get("/api/changelog")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Changelog", r.json["changelog"])

if __name__ == "__main__":
    unittest.main()
