import os
import json
from pprint import pprint

current_directory = os.getcwd()

filess = os.listdir(current_directory)

json_files = list(filter(lambda x: x.endswith(".json"), filess))

data = {}

for f in json_files:
    with open(f, "r") as file:
        try:
            data[f] = json.load(file)
        except json.decoder.JSONDecodeError:
            print(f"Failed to load {f}")

connection_issue = 0
total = 0
failed = 0
failed_runs = []
for testcase, runs in data.items():
    elapsed_times = []
    for i, r in enumerate(runs):
        total += 1

        if isinstance(r, dict) and 'elapsed_time' in r:
            elapsed_times.append(r['elapsed_time'])

        if r.get("error") == "No chat threads found.":
            connection_issue += 1
        elif r.get("diff_result"):
            failed += 1
            failed_runs.append(f"{testcase}. Run {i + 1}")
    if elapsed_times:
        print(f"Average Elapsed Time for '{testcase}' Test Case Runs:", sum(elapsed_times)/len(elapsed_times))
    else:
        print(f"No elapsed_time found for '{testcase}' Test Case Runs. Possible reason - incorrect test case type.")
success = total - connection_issue - failed
print(f"Success rate: {success / total * 100:.2f} %")
print(f"Connection failure rate: {connection_issue / total * 100:.2f} %")
print(f"Other failure rate: {failed / total * 100:.2f} %")
from pprint import pp

print("Failed runs")
pp(failed_runs)