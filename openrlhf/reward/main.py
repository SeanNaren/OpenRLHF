import argparse
import multiprocessing
import os
import re
import resource
import subprocess
import traceback

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from tqdm import tqdm

app = FastAPI()

parser = argparse.ArgumentParser()
parser.add_argument("--limit_tests", type=int, default=10)
parser.add_argument("--port", type=int, default=5000, help="Port number for the server")
parser.add_argument("--host", type=str, default="0.0.0.0", help="IP for the server")
parser.add_argument("--workers", type=int, default=16, help="Number of workers for the server")
args = parser.parse_args()


def execute_code(generated_code, std_input, timeout):
    """
    Execute Python code in a subprocess using in-memory strings.

    :param generated_code: Python code as a string.
    :param std_input: Input to be piped to the Python process.
    :param timeout: Timeout in seconds for code execution.
    :return: A dict containing stdout, stderr, and a traceback message (if any).
    """

    def set_limits():
        # Set resource limits (10 GB memory limit as in your original function)
        limit = 1024 * 1024 * 1024 * 10  # 10 GB
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
        resource.setrlimit(resource.RLIMIT_DATA, (limit, limit))

    try:
        # Start a subprocess that runs the generated Python code
        process = subprocess.Popen(
            ["python3", "-c", generated_code],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            preexec_fn=set_limits
        )
        # Communicate std_input to the process and capture its output
        stdout, stderr = process.communicate(input=std_input, timeout=timeout)
        return {"stdout": stdout, "stderr": stderr, "traceback": ""}
    except subprocess.TimeoutExpired as e:
        process.kill()
        return {"stdout": "", "stderr": "", "traceback": f"TimeoutExpired: {e}"}
    except Exception as e:
        return {"stdout": "", "stderr": "", "traceback": str(e)}


def extract_ids(text):
    lines = text.strip().split('\n')
    for line in lines:
        match = re.search(r'^(\d+)\s*([A-Za-z0-9]+)$', line.strip())
        if match:
            return match.groups()
    return None, None


def evaluate_test_case(seq, test_data, test_limit, execute_function):
    inputs = test_data['input']
    outputs = test_data['output']

    if len(inputs) != len(outputs):
        raise ValueError("Input and output lists in a solution must be of the same length")

    limited_tests = list(zip(inputs, outputs))[:min(len(inputs), test_limit)]
    code_matches = re.findall(r"```python\n(.*?)```", seq, re.DOTALL)
    if not code_matches:
        return 0.0

    code = code_matches[-1]
    tests_passed = 0
    for test_input, expected_output in limited_tests:
        test_input = test_input.replace("\r\n", "\n").replace("\r", "\n").replace(" \n", "\n")
        expected_output = expected_output.replace("\r\n", "\n").replace("\r", "\n").replace(" \n", "\n")

        output = execute_function(code, std_input=test_input, timeout=0.5)
        stdout = output['stdout'].replace("\r\n", "\n").replace("\r", "\n").replace(" \n", "\n")
        if expected_output == stdout:
            tests_passed += 1

    total_tests = len(limited_tests)
    return tests_passed / total_tests if total_tests > 0 else 0.0


def execute(generated_code, std_input, timeout):
    try:
        output = execute_code(generated_code, std_input, timeout)
        return {"process_status": "completed", "execution": "SUCCESS", "stdout": output.get("stdout", ""),
                "stderr": output.get("stderr", ""), "traceback": output.get("traceback", "")}
    except TimeoutError:
        return {"process_status": "timeout", "execution": "FAILED", "stdout": "TimeoutError", "stderr": "TimeoutError",
                "traceback": "TimeoutError"}
    except Exception as e:
        return {"process_status": "error", "execution": "FAILED", "stdout": "", "stderr": str(e),
                "traceback": traceback.format_exc()}


class RewardModelProxy:
    def __init__(self, test_limit: int):
        self.test_limit = test_limit

    def get_reward(self, queries, input_dicts):
        test_data = [(seq, input_dict['solution'], self.test_limit, execute) for seq, input_dict in zip(queries, input_dicts)]
        with multiprocessing.Pool(processes=len(queries)) as pool:
            rewards = pool.starmap(evaluate_test_case, tqdm(test_data, total=len(queries)))
        return rewards


@app.on_event("startup")
def init_stuff() -> None:
    global reward_model
    reward_model = RewardModelProxy(args.limit_tests)


@app.post("/get_reward")
async def get_reward(request: Request):
    data = await request.json()
    queries = data.get("query")
    input_dict = data.get("input_dict")
    rewards = reward_model.get_reward(queries, input_dict)
    result = {"rewards": rewards}
    print(f"Sent JSON: {result}")
    return JSONResponse(result)


if __name__ == "__main__":
    port = args.port
    workers = args.workers
    if os.environ.get("LISTEN_PORT"):
        print(f"Setting port to {os.environ['LISTEN_PORT']}")
        port = int(os.environ["LISTEN_PORT"])
    if os.environ.get("RM_WORKERS"):
        print(f"Setting workers to {os.environ['RM_WORKERS']}")
        workers = int(os.environ["RM_WORKERS"])
    uvicorn.run("main:app", host=args.host, port=port, log_level="info", workers=workers)
