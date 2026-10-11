import time


class ProcessTestResult:
    """
    Class to store and retrieve test results
    """

    def __init__(self, testsuite_name: str):
        self.testsuite_name = testsuite_name
        self.success_count = 0
        self.failure_count = 0
        self.test_results: list[dict] = []
        self.start_time = time.perf_counter()
        self.test_time = self.start_time
        self.duration = 0
        self.test_counter = 0

    def process(
        self,
        test_case_name: str,
        test_ok: bool,
        test_output: str | list,
        test_step_name: str = "",
    ):
        """
        Process test result.
        Calculates success and failure count and stores these metrics, result outputand identifiers in test_result
        The test results can be retrieved later on in method get_test_results
        """
        # --- Calculations
        end_time = time.perf_counter()
        test_duration = end_time - self.test_time
        self.test_time = end_time
        self.duration = end_time - self.start_time
        self.test_counter += 1

        if test_ok:
            self.success_count += 1
        else:
            self.failure_count += 1

        result_output_list: list[str] = []

        if isinstance(test_output, str):
            result_output_list.append(test_output)
        else:
            result_output_list = list(test_output)

        test_result = {
            "test_case_name": test_case_name,
            "test_step_name": test_step_name,
            "test_counter": self.test_counter,
            "test_ok": test_ok,
            "test_duration": test_duration,
            "test_output": result_output_list,
        }
        self.test_results.append(test_result)

    def get_test_results(self) -> list[dict]:
        return self.test_results
