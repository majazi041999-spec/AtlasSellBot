"""Preparing artwork and drafts cannot send or alter business rewards/history."""
import base64
import importlib.util
import sqlite3
import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("prepare_campaigns", ROOT / "tools/prepare_campaigns_20261016.py")
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)


class CampaignPreparationTests(unittest.TestCase):
    def test_idempotent_preparation_preserves_owner_media_rewards_and_send_state(self):
        from core.database import SCHEMA
        with tempfile.TemporaryDirectory() as folder:
            database = Path(folder) / "test.db"
            db = sqlite3.connect(database)
            db.executescript(SCHEMA)
            photo = BytesIO()
            Image.new("RGB", (100, 100), "green").save(photo, "PNG")
            original = "data:image/png;base64," + base64.b64encode(photo.getvalue()).decode()
            db.execute("INSERT INTO custom_campaigns(slug,title,message,photo,status,sent_count) VALUES(?,?,?,?,?,?)",
                       ("winback_blast", "Owner campaign", "Owner message", original, "sent", 42))
            db.execute("INSERT INTO custom_campaigns(slug,title,message) VALUES('referral_push','Referral','Old amounts')")
            db.execute("INSERT INTO settings(key,value) VALUES('referral_per_referral_amount','15000')")
            db.commit()
            dry = prepare.prepare(database, False)
            self.assertEqual(2, len(dry["new_drafts"]))
            self.assertEqual(2, db.execute("SELECT COUNT(*) FROM custom_campaigns").fetchone()[0])
            prepare.prepare(database, True)
            prepare.prepare(database, True)
            self.assertEqual(4, db.execute("SELECT COUNT(*) FROM custom_campaigns").fetchone()[0])
            self.assertEqual((original, "sent", 42), db.execute("SELECT photo,status,sent_count FROM custom_campaigns WHERE slug='winback_blast'").fetchone())
            self.assertEqual("15000", db.execute("SELECT value FROM settings WHERE key='referral_per_referral_amount'").fetchone()[0])
            self.assertIn("{referral_rewards}", db.execute("SELECT message FROM custom_campaigns WHERE slug='referral_push'").fetchone()[0])
            self.assertEqual(0, db.execute("SELECT COUNT(*) FROM campaign_events").fetchone()[0])
            db.close()


if __name__ == "__main__":
    unittest.main()
