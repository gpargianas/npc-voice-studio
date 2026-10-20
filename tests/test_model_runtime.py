import unittest

from src.model_runtime import ModelUnavailableError, OmniVoiceRuntime


class FakeService:
    device = "cuda:0"


class ModelRuntimeTests(unittest.TestCase):
    def test_service_is_initialized_only_once(self) -> None:
        calls = 0

        def create_service() -> FakeService:
            nonlocal calls
            calls += 1
            return FakeService()

        runtime = OmniVoiceRuntime(create_service)

        first = runtime.initialize()
        second = runtime.initialize()

        self.assertIs(first, second)
        self.assertIs(runtime.require(), first)
        self.assertEqual(calls, 1)

    def test_failure_is_retained_without_repeated_load_attempts(self) -> None:
        calls = 0

        def fail_to_create() -> FakeService:
            nonlocal calls
            calls += 1
            raise RuntimeError("CUDA out of memory")

        runtime = OmniVoiceRuntime(fail_to_create)

        with self.assertLogs("src.model_runtime", level="ERROR"):
            self.assertIsNone(runtime.initialize())
        self.assertIsNone(runtime.initialize())
        with self.assertRaises(ModelUnavailableError) as raised:
            runtime.require()

        self.assertIn("GPU memory", str(raised.exception))
        self.assertEqual(calls, 1)


if __name__ == "__main__":
    unittest.main()
