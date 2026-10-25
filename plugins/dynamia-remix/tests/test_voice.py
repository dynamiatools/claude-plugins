import datetime
import os
import tempfile
import unittest

from _load import load

voice = load("remix-voice")
TODAY = datetime.date(2026, 10, 25)


def row(text, src="app store", rating="1", url="https://x.test/1", date="2026-09-01"):
    return {"source": src, "url": url, "date": date, "rating": rating, "text": text}


class VoiceTest(unittest.TestCase):
    def test_rows_without_link_are_dropped(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "r.csv")
            open(p, "w").write("source,url,date,rating,text\nA,,2026-01-01,1,too expensive\nA,https://x.test/2,2026-01-01,1,too expensive\n")
            rows, dropped = voice.load(p)
            self.assertEqual((len(rows), dropped), (1, 1))

    def test_thin_needs_three_reviews_and_two_sources(self):
        rows = [row("so expensive", "a"), row("price hike", "a"), row("pricing is bad", "a")]
        ranked = dict(voice.rank(rows, voice.THEMES, TODAY))
        self.assertTrue(ranked["price and billing"]["thin"])
        rows.append(row("too expensive", "b"))
        ranked = dict(voice.rank(rows, voice.THEMES, TODAY))
        self.assertFalse(ranked["price and billing"]["thin"])

    def test_low_and_recent_weigh_more(self):
        old_good = row("slow", rating="5", date="2020-01-01")
        new_bad = row("slow", rating="1")
        self.assertGreater(voice.weight(new_bad, TODAY), voice.weight(old_good, TODAY))

    def test_quote_is_verbatim_with_link(self):
        text = "It keeps CRASHING, don't buy!"
        out = voice.render(voice.rank([row(text)], voice.THEMES, TODAY), 1, 0)
        self.assertIn('"%s"' % text, out)
        self.assertIn("https://x.test/1", out)


if __name__ == "__main__":
    unittest.main()
