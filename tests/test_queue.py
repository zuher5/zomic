import os
import tempfile
import unittest

from scraper.queue import JobQueue


class JobQueueTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.path = os.path.join(self.tmpdir, "jobs.db")
        self.queue = JobQueue(self.path)

    def test_enqueue_and_dedupe(self):
        j1 = self.queue.enqueue("scrape_comic", {"slug": "x"})
        j2 = self.queue.enqueue("scrape_comic", {"slug": "x"})
        j3 = self.queue.enqueue("scrape_comic", {"slug": "y"})
        self.assertEqual(j1, j2)
        self.assertNotEqual(j1, j3)
        self.assertEqual(self.queue.counts()["queued"], 2)

    def test_claim_complete_flow(self):
        jid = self.queue.enqueue("scrape_comic", {"slug": "x"})
        job = self.queue.claim_next()
        self.assertEqual(job["id"], jid)
        self.assertEqual(job["payload"], {"slug": "x"})
        self.assertEqual(job["attempts"], 1)
        self.queue.complete(jid)
        self.assertEqual(self.queue.counts()["completed"], 1)
        self.assertIsNone(self.queue.claim_next())

    def test_fail_and_retry(self):
        jid = self.queue.enqueue("scrape_comic", {"slug": "x"})
        self.queue.claim_next()
        self.queue.fail(jid, "boom")
        self.assertEqual(self.queue.counts()["failed"], 1)
        retried = self.queue.retry_failed()
        self.assertEqual(retried, [jid])
        self.assertEqual(self.queue.counts()["queued"], 1)
        self.assertEqual(self.queue.counts()["failed"], 0)

    def test_list_jobs(self):
        self.queue.enqueue("download_images", {})
        jobs = self.queue.list_jobs()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["type"], "download_images")


if __name__ == "__main__":
    unittest.main()