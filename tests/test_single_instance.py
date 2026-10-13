from pathlib import Path
import tempfile
import unittest

from app.utils.single_instance import SingleInstanceLock


class SingleInstanceLockTest(unittest.TestCase):
    def test_second_instance_is_refused_until_first_exits(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "incubator.lock"
            with SingleInstanceLock(path):
                with self.assertRaises(RuntimeError):
                    SingleInstanceLock(path).__enter__()

            with SingleInstanceLock(path):
                pass
            self.assertTrue(path.exists())


if __name__ == "__main__":
    unittest.main()
