# /usr/bin/env python3
import os
import sys
import subprocess
import time
import random
from threading import Lock, Semaphore, Thread
from enum import Enum

# --- CONFIGURATION PARAMETERS ---

# how many times to run each test
NUM_EXECUTIONS = 50

# max number of concurrently running jobs. Setting this to 1 makes the tests run sequentially.
NUM_CONCURRENT = 50

# how many characters wide the gui is (it's actually 4 chars wider than this)
LINE_WIDTH = 50

# Add a test name here to ignore it. Ex: ['TestUnreliable'] will ignore that test.
IGNORE = []

# Add a test name here to force it to run sequentially. Useful for if you suspect that running tests concurrently might be causing a bug.
FORCE_SEQ = []

# Argument for `go test -timeout.` If you'd like to be extra cautious about the performance of your code, you can reduce this.
TIMEOUT = "2m"

# This script saves the logs of failing tests to disk. This is max number of failing jobs for which the logs will be saved.
# MAX_LOGFILES = NUM_EXECUTIONS will save all logs
MAX_LOGFILES = 5

# --------------------------------

# --- ANSI CODES ---
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"

GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
# ------------------


class JobState(Enum):
    WAITING = f"{DIM}w{RESET}"
    RUNNING = f"{BOLD}r{RESET}"
    PASSED = f"{GREEN}P{RESET}"
    FAILED = f"{RED}F{RESET}"


PADDING_SPACE = LINE_WIDTH - (NUM_EXECUTIONS % LINE_WIDTH)
PERFECT = (NUM_EXECUTIONS % LINE_WIDTH) == 0  # no padding line needed

force_seq = False


# Encapsulates the state for NUM_EXECUTIONS runs of one test
class TestState:
    assignment_name: str
    test_name: str
    job_states: list[JobState]
    sem: Semaphore  # controlls number of processes running at once
    stdout_lock: Lock  # mutex over stdout
    _first_print: bool
    count_lock: Lock  # mutex over stdout
    total_runs: int
    total_successes: int
    log_files: list[str] # a list of log files kept for failed tests.

    def __init__(self, assignment_name: str, test_name: str):
        self.test_name = test_name
        self.assignment_name = assignment_name
        self._first_print = True

        # initialize all states to waiting
        self.job_states = [JobState.WAITING] * NUM_EXECUTIONS
        self.sem = Semaphore(0)
        self.stdout_lock = Lock()
        self.count_lock = Lock()
        self.total_runs = 0
        self.total_successes = 0
        self.log_files = []

    def change_state(self, job_id: int, state: JobState):
        self.stdout_lock.acquire()
        self.job_states[job_id] = state

        if not self._first_print:
            clear_lines((NUM_EXECUTIONS // LINE_WIDTH) + 1 if PERFECT else 2)
        else:
            self._first_print = False

        for i, state in enumerate(self.job_states):
            if i % LINE_WIDTH == 0:
                sys.stdout.write("[ ")
            sys.stdout.write(state.value)
            if i % LINE_WIDTH == LINE_WIDTH - 1:
                sys.stdout.write(" ]\n")

        if NUM_EXECUTIONS % LINE_WIDTH != 0:
            sys.stdout.write(" " * PADDING_SPACE + " ]\n")

        with self.count_lock:
            message = f"[ Passed: {self.total_successes} / {self.total_runs} ]"
            padding = LINE_WIDTH + 4 - len(message)
            print(" " * padding + message)

        self.stdout_lock.release()

    # job tells state result. Return true if we should save the logfile to disk
    def announce_result(self, success: bool, log=None) -> bool:
        with self.count_lock:
            self.total_runs += 1
            if success:
                self.total_successes += 1
            if log and len(self.log_files) < MAX_LOGFILES:
                self.log_files.append(log)
                return True
        return False


# run one of N tests associated with an assignment, NUM_EXECUTIONS times
def run_test(assignment_name: str, test_name: str):
    print(f"\n Running {test_name} {NUM_EXECUTIONS} times:")
    state = TestState(assignment_name, test_name)

    threads: list[Thread] = []
    for job in range(NUM_EXECUTIONS):
        t = Thread(target=do_job, args=(job, state))
        threads.append(t)
        t.start()

    for _ in range(1 if force_seq else NUM_CONCURRENT):
        # stagger the process starts, so they don't all start and finish together
        state.sem.release()
        time.sleep(abs(random.gauss(0.1, 0.025)))

    for t in threads:
        t.join()

    if state.log_files:
        print(f'\n {YELLOW}{BOLD}Saved {len(state.log_files)} logs from failed tests:{RESET}')
        for log in state.log_files:
            print(f' {log}')
        print('') # print newline


def do_job(job_num: int, state: TestState):
    state.sem.acquire()

    if exited:
        state.sem.release()
        return

    # navigate to the correct directory for the assignment
    # run go test on test_name, timing out after 2 minutes
    # redirect output to a log file
    command = f'cd src/{state.assignment_name} && go test -run "^{state.test_name}$" -timeout {TIMEOUT}'

    state.change_state(job_num, JobState.RUNNING)

    process = subprocess.Popen(
        command,
        shell=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    output, _ = process.communicate()

    success = process.returncode == 0

    if success:
        state.announce_result(success)
        state.change_state(job_num, JobState.PASSED)
    else:
        logfile_name = f"{state.test_name}-{state.assignment_name}-job{job_num}-failure.log"
        should_save_log = state.announce_result(success, logfile_name)
        state.change_state(job_num, JobState.FAILED)

        if should_save_log:
            with open(logfile_name, "w") as f:
                f.write(filter_garbage(output))

    state.sem.release()


GARBAGE = [
    "paxos Dial() failed:",
    "unexpected EOF",
    "write unix ->",
    "read unix ->",
    "2022/",
    "reading body EOF",
]


# remove garbage from logs. adapted from original script
def filter_garbage(out: bytes) -> str:
    lines = out.decode("utf-8").splitlines(keepends=True)
    filtered_lines = filter(
        lambda l: not any([l.startswith(g) for g in GARBAGE]), lines
    )
    return "".join(filtered_lines)


def main():
    cwd = os.getcwd()
    if not "src" in os.listdir(cwd):
        print(
            f"Could not find src directory in the current workding directory. cwd: {cwd}"
        )
        sys.exit(1)

    if len(sys.argv) <= 1:
        print(
            "Specify which assignment you'd like to test as an argument to this script.\n\n"
            "Ex:\n"
            "python3 batch-test.py mapreduce\n\n"
            f"The assignment should be one of {list(TEST_NAMES.keys())}"
        )
        sys.exit(1)

    assignment = sys.argv[1]
    if not assignment in TEST_NAMES.keys():
        print(
            f"Unknown assignment {assignment}. Should be one of {list(TEST_NAMES.keys())}"
        )
        sys.exit(1)

    print(" --- Blake's 4113 BatchTester! ---\n")

    if assignment == "mapreduce":
        global NUM_CONCURRENT
        NUM_CONCURRENT = 1
        print(
            f" {YELLOW}!! Homework 1 cannot be tested in parallel. Running sequentially. !!{RESET}\n"
        )

    print(f" N = {NUM_EXECUTIONS} PAR = {NUM_CONCURRENT}")
    print(f" {JobState.WAITING.value}: Waiting")
    print(f" {JobState.RUNNING.value}: Running")
    print(f" {JobState.PASSED.value}: Passed")
    print(f" {JobState.FAILED.value}: Failed")

    global force_seq
    for test in TEST_NAMES[assignment]:
        if test in IGNORE:
            print(f"\n {YELLOW}!! ignoring {test} !!{RESET}")
            continue

        if test in FORCE_SEQ:
            print(f"\n {YELLOW}!! forcing concurrent execution for {test} !!{RESET}")
            force_seq = True
        else:
            force_seq = False

        run_test(assignment, test)


# terminal hax to clear the last n lines
def clear_lines(num_lines):
    sys.stdout.write(f"\033[{num_lines}F")
    sys.stdout.write("\033[J")


TEST_NAMES = {
    "mapreduce": ["TestBasic", "TestOneFailure", "TestManyFailures"],
    "viewservice": ["Test1"],
    "pbservice": [
        "TestBasicFail",
        "TestAtMostOnce",
        "TestFailPut",
        "TestConcurrentSame",
        "TestConcurrentSameUnreliable",
        "TestRepeatedCrash",
        "TestRepeatedCrashUnreliable",
        "TestPartition1",
        "TestPartition2",
    ],
    "paxos": [
        "TestBasic",
        "TestDeaf",
        "TestForget",
        "TestManyForget",
        "TestForgetMem",
        "TestRPCCount",
        "TestMany",
        "TestOld",
        "TestManyUnreliable",
        "TestPartition",
        "TestLots",
    ],
    "kvpaxos": [
        "TestBasic",
        "TestDone",
        "TestPartition",
        "TestUnreliable",
        "TestHole",
        "TestManyPartition",
    ],
    "shardmaster": ["TestBasic", "TestUnreliable", "TestFreshQuery"],
    "shardkv": [
        "TestBasic",
        "TestMove",
        "TestLimp",
        "TestConcurrent",
        "TestConcurrentUnreliable",
    ],
}

exited = False

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        exited = True
        sys.exit()
