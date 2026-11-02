"""Run on GitHub Actions after update; pure stdlib."""
import json
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

class TestLiveData(unittest.TestCase):
    def test_site_snapshot(self):
        latest=json.loads((ROOT/'data/latest.json').read_text(encoding='utf-8'))
        hist=json.loads((ROOT/'data/history.json').read_text(encoding='utf-8'))
        self.assertGreaterEqual(len(latest['models']), 50)
        self.assertTrue(all(m['score']['value'] is not None for m in latest['models']))
        self.assertEqual(len(set(m['id'] for m in latest['models'])),len(latest['models']))
        self.assertTrue(hist['dates'][-1] in hist['by_date'])
        for m in latest['models']:
            for key in ('input','output','cached'):
                self.assertGreaterEqual(m['prices'][key],0,m['id'])

if __name__=='__main__':unittest.main()
