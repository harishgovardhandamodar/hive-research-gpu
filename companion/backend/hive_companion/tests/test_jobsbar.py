from __future__ import annotations

import unittest

from hive_companion.jobsbar import extract_fox_job_ids


def _step(result) -> dict:
    return {"kind": "step", "context": {"tool": "survey.start", "result": result}}


class TestExtractFoxJobIds(unittest.TestCase):
    def test_from_nested_dict(self) -> None:
        eps = [_step({"status": "ok", "result": {"job_id": "abc123def456", "status": "queued"}})]
        self.assertEqual(extract_fox_job_ids(eps), ["abc123def456"])

    def test_from_stringified_result(self) -> None:
        eps = [_step('{"status": "ok", "result": {"job_id": "abc123def456", "status": "queued"}}')]
        self.assertEqual(extract_fox_job_ids(eps), ["abc123def456"])

    def test_dedupes_newest_first_and_limits(self) -> None:
        eps = [
            _step({"result": {"job_id": "aaa111111111"}}),
            _step({"result": {"job_id": "bbb222222222"}}),
            _step({"result": {"job_id": "aaa111111111"}}),
        ]
        # newest first: the third episode re-mentions aaa
        self.assertEqual(extract_fox_job_ids(eps, limit=2), ["aaa111111111", "bbb222222222"])

    def test_ignores_other_tools(self) -> None:
        eps = [{"kind": "step", "context": {"tool": "rag.query", "result": {"result": {"job_id": "xxx000000000"}}}}]
        self.assertEqual(extract_fox_job_ids(eps), [])


if __name__ == "__main__":
    unittest.main()
