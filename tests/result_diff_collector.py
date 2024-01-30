import json
import os

import requests

results_path = os.path.join(os.path.dirname(__file__), "..", "report")

test_results = os.listdir(results_path)
total_diffs = {}
for test_result in test_results:
    file_path = f"{results_path}/{test_result}"
    f = open(file_path)
    data = json.load(f)
    total_diffs[test_result] = []
    successful = 0
    for element in data:
        diff = element["diff_result"]
        if diff:
            transaction_id = element["transaction_id"]

            try:
                url = f"https://exchange-prod.staircaseapi.com/chatbot/threads?transaction_id={transaction_id}"
                headers = {
                    'Content-Type': 'application/json',
                    'x-api-key': '2d1e8c76-7d96-457a-bcaf-6d3f41b71afa'
                }
                response = requests.get(url=url, headers=headers)
                response.raise_for_status()
                thread_id = response.json()["chat_threads"][0]["open_ai_thread_id"]
                playground_link = f"https://platform.openai.com/playground?thread={thread_id}"
                total_diffs[test_result].append({"playground_link": playground_link, "cause": diff})
            except Exception as e:
                print(e)
        else:
            successful = successful + 1

    print(test_result)
    print(f"Total: {len(data)}, Successful: {successful} Rate: {float(successful/len(data))}")
    print(f"Links and root causes for errors in {test_result}")
    print(json.dumps(total_diffs[test_result], indent=2))
