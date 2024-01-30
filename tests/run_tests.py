import argparse
import concurrent.futures
import io
import json
import os
import time
from http import HTTPStatus
from urllib.parse import urlsplit, quote

import requests
import yaml
from dotenv import load_dotenv
from deepdiff import DeepDiff
from openai import OpenAI


NUMBER_OF_RUNS_PER_TEST_CASE = 10
MODEL_PRICING = {
    "gpt-4-0125-preview": {"input_tokens": 0.01, "output_tokens": 0.03},
    "gpt-4-1106-preview": {"input_tokens": 0.01, "output_tokens": 0.03},
    "gpt-4-1106-vision-preview": {"input_tokens": 0.01, "output_tokens": 0.03},
    "gpt-4": {"input_tokens": 0.03, "output_tokens": 0.06},
    "gpt-4-32k": {"input_tokens": 0.06, "output_tokens": 0.12},
    "gpt-3.5-turbo-1106": {"input_tokens": 0.001, "output_tokens": 0.002},
    "gpt-3.5-turbo-instruct": {"input_tokens": 0.0015, "output_tokens": 0.002},
}
# Alias for gpt-3.5-turbo for now is
MODEL_PRICING['gpt-3.5-turbo'] = MODEL_PRICING['gpt-3.5-turbo-1106']


def start_application(assistant_name, prompts, conversation_name, transaction_id):
    print(f"[{transaction_id}] Start handling {conversation_name}")
    conversation_log = []

    print(f"[{transaction_id}] Creating Thread ID")

    response = make_request()(
        url="chatbot/threads", method="POST", json={"transaction_id": transaction_id}
    )

    if response.status_code != 201:
        print(response.content)
        raise Exception(response.content)

    thread_id = response.json()["id"]

    for i, prompt in enumerate(prompts):
        print(f'[{transaction_id}] Hanlding prompt #{i+1}')
        if isinstance(prompt, dict) and prompt.get('type') == 'sleep':
            print(f'[{transaction_id}] Going to sleep for {prompt.get("sleep")} seconds')
            time.sleep(prompt.get('sleep'))
            continue
        while True: # until run is completed
            print(f'[{transaction_id}] User Message:', prompt, sep='\n', end='\n\n')
            file_id = None
            if isinstance(prompt, dict) and 'blob_id' in prompt:
                blob_id = prompt['blob_id']
                download_url = create_download_url_for_blob(blob_id)
                print(f'[{transaction_id}] Download URL:', download_url)
                file_data_stream = requests.get(download_url, stream=True)

                data = io.BytesIO()
                for chunk in file_data_stream.iter_content(chunk_size=8192):
                    data.write(chunk)
                data.seek(0)

                file = client.files.create(file=data, purpose='assistants')
                print(f'[{transaction_id}] Successfully uploaded file {blob_id} for Assistant. File ID - {file.id}')
                file_id = file.id

            conversation_log.append({'sender': 'user', 'message': prompt})

            payload = {
                'thread_id': thread_id,
                'role': 'user',
                'content': prompt,
                'assistant_name': assistant_name,
                'transaction_id': transaction_id
            }
            if file_id:
                payload['file_ids'] = [file_id]
                payload['content'] = prompt.get('message')

            sc_run_id = make_request()(
                url='chatbot/runs',
                method='POST',
                json=payload
            ).json()['id']

            while True:
                print(f'[{transaction_id}] Waiting for response')
                response = make_request()(
                    url=f'chatbot/runs/{sc_run_id}',
                    method='GET'
                ).json()
                time.sleep(5)

                status = response.get('status')
                openai_run_id = response.get('openai_id')

                if status in ('completed', 'expired', 'failed'):
                    break

            if status == 'completed':
                break
            if status in ('expired', 'failed'):
                print(f'[{transaction_id}] Run \'{sc_run_id}\' is {status}, running again.')
            else:
                print(f'[{transaction_id}] Run \'{sc_run_id}\' has unexpected \'{status}\', running again')

        messages = client.beta.threads.messages.list(thread_id=thread_id)
        bot_replies = [
            {"sender": "assistant", "raw_content": json.loads(i.model_dump_json())}
            for item in messages.data
            for i in item.content
            if item.role == "assistant" and item.run_id == openai_run_id
        ][::-1]
        print(f"[{transaction_id}] Bot replies:", bot_replies, sep="\n", end="\n\n")

        conversation_log.extend(bot_replies)

    return thread_id, conversation_log


def create_download_url_for_blob(blob_id):
    return make_request()(
        url=f"persistence/blobs/{blob_id}/presigned-urls/download",
        method="PUT",
        json={"presign_url_ttl": 604800},
    ).json()["download"]["url"]


def get_containers(frame):
    containers = []
    context = frame.get("@context")
    for item, value in context.items():
        if type(value) == dict:
            if value.get("@container") == "@set":
                containers.append(item)
    return containers


def find_container(_type, frame):
    containers = get_containers(frame)
    for container in containers:
        container_type = frame[container].get("@type")[0]
        if container_type == _type:
            return container
    return None


def retrieve_stored_data(make_request, transaction_id):
    url = "chatmtg-util/query_transaction_data"
    response = make_request(url, method="POST", json={"transaction_id": transaction_id})
    recorded_data_so_far = response.json()["message"]["all_recorded_data_so_far"]
    return recorded_data_so_far


def create_transaction(make_request):
    response = make_request("persistence/transactions", method="POST")
    assert response.status_code == HTTPStatus.CREATED
    transaction_id = response.json()["transaction_id"]
    return transaction_id


def make_request(max_attemts=20, acc_delay=5):
    def f(url, **options) -> requests.Response:
        target = urlsplit(TARGET_URL)
        url = f"{target.scheme}://{target.hostname}/{url}"
        headers = options.pop("headers", {})
        headers["x-api-key"] = X_API_KEY

        attempts = 0
        timeout = acc_delay
        while attempts < max_attemts:
            response = requests.request(url=url, headers=headers, **options)
            if response.status_code >= 400:
                print(f'Incorrect status code received for {url}, options passed - {options}, will try again. Reason - {response.content}')
                attempts += 1
                if attempts == max_attemts:
                    raise Exception(f"Request for {url} has failed. {response.content}")
                time.sleep(timeout)
                timeout += acc_delay
            else:
                return response

    return f


def calculate_consumption(thread_id):
    is_code_interpreter_used = False
    tokens_usage = {"input_tokens": 0, "output_tokens": 0}
    runs = client.beta.threads.runs.list(thread_id=thread_id, order="desc")

    if not runs.data:
        raise Exception(f"No runs found for {thread_id} thread")

    latest_run = runs.data[0]

    run_steps = client.beta.threads.runs.steps.list(
        thread_id=thread_id, run_id=latest_run.id, limit=100
    )
    for run_step in run_steps.data:
        tokens_usage['input_tokens'] += run_step.model_extra.get('usage', {}).get('prompt_tokens', 0)
        tokens_usage['output_tokens'] += run_step.model_extra.get('usage', {}).get('completion_tokens', 0)
        if run_step.step_details.type != "tool_calls":
            continue
        for tool_call in run_step.step_details.tool_calls:
            if tool_call.type == "code_interpreter":
                is_code_interpreter_used = True
                break

    return tokens_usage, is_code_interpreter_used


def process_test(test_case, attempt, assistant_name):
    print("Create Transaction")
    transaction_id = create_transaction(make_request())

    if test_case.get("init_collection"):
        print("Create Init Collection")
        make_request()(
            url=f"persistence/transactions/{transaction_id}/collections",
            method="POST",
            json={
                "metadata": {"version": 3, "validation": False},
                "data": test_case.get("init_collection"),
            },
        )
        time.sleep(1)

    conversation_name = test_case.get("conversation_name")

    prompts = test_case.get("prompts")

    conversation_started_at = time.time()
    thread_id, conversation_log = start_application(assistant_name, prompts, conversation_name, transaction_id)
    elapsed_time_for_running_conversation = time.time() - conversation_started_at
    tokens_usage, is_code_interpreter_used = calculate_consumption(thread_id)
    if "expected_v3" in test_case:
        print(
            "Warning: Persistence tests are deprecated, make sure to use Function Call tests"
        )
        recorded_data = retrieve_stored_data(make_request(), transaction_id)

        exclude_regex_paths = [
            f"\\['{item}'\\]" for item in test_case["exclude_regex_paths"]
        ]

        diff_result = DeepDiff(
            test_case["expected_v3"],
            recorded_data,
            ignore_order=True,
            exclude_paths=["root['chat_threads']"],
            exclude_regex_paths=exclude_regex_paths,
        )
        return {
            'conversation_name': test_case['conversation_name'],
            'assistant_name': test_case['assistant_name'],
            'transaction_id': transaction_id,
            'prompts': test_case['prompts'],
            'expected': test_case['expected_v3'],
            'actual': recorded_data,
            'diff_result': json.loads(diff_result.to_json()),
            'conversation_log': conversation_log,
            'test_type': 'Persistence',
            'elapsed_time': elapsed_time_for_running_conversation,
            "tokens_usage": tokens_usage,
            "is_code_interpreter_used": is_code_interpreter_used

        }
    elif "expected_function_calls" in test_case:
        runs = client.beta.threads.runs.list(thread_id=thread_id, order="desc")

        if not runs.data:
            raise Exception(f"No runs found for {thread_id} thread")

        latest_run = runs.data[0]

        run_steps = client.beta.threads.runs.steps.list(
            thread_id=thread_id, run_id=latest_run.id, limit=100
        )

        tools_called = []
        for run_step in run_steps.data:
            if run_step.step_details.type != "tool_calls":
                continue
            for tool_call in run_step.step_details.tool_calls:
                if tool_call.type != "function":
                    continue
                tools_called.append(
                    {
                        "name": tool_call.function.name,
                        "arguments": json.loads(tool_call.function.arguments),
                    }
                )

        exclude_regex_paths = [
            f"\\['{item}'\\]" for item in test_case["exclude_regex_paths"]
        ]

        diff_result = DeepDiff(
            test_case["expected_function_calls"],
            tools_called,
            ignore_order=True,
            exclude_paths=["root['chat_threads']"],
            exclude_regex_paths=exclude_regex_paths,
        )

        return {
            'conversation_name': test_case['conversation_name'],
            'assistant_name': test_case['assistant_name'],
            'transaction_id': transaction_id,
            'prompts': test_case['prompts'],
            'expected': test_case['expected_function_calls'],
            'actual': tools_called,
            'diff_result': json.loads(diff_result.to_json()),
            'conversation_log': conversation_log,
            'test_type': 'Function Call',
            'elapsed_time': elapsed_time_for_running_conversation,
            "tokens_usage": tokens_usage,
            "is_code_interpreter_used": is_code_interpreter_used

        }
    else:
        print("Unsupported test type. Make sure to use 'Function Call' test type")
        return None


def save_results(results):
    for filename, result in results.items():
        with open(f"{args.output_dir}/{filename}.json", "w") as file:
            json.dump(result, file, indent=4)


def get_configurable_value(name, possible_values, default):
    for possible_value in possible_values:
        if possible_value:
            return possible_value
    print(f"'{name}' value was not provided, using default one - {default}")
    return default


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "test_suit_dir", type=str, help="Path to the dir with test suit"
    )
    parser.add_argument("output_dir", type=str, help="Path to the dir with test report")
    parser.add_argument(
        "--runs_per_case",
        type=int,
        default=NUMBER_OF_RUNS_PER_TEST_CASE,
        help="Number of Runs per Test Case",
    )
    parser.add_argument(
        "--openai_api_key", type=str, default=None, help="OpenAI Api Key"
    )
    parser.add_argument("--assistant_name", type=str, default=None, help="Assistant ID")

    args = parser.parse_args()

    load_dotenv()

    OPENAI_API_KEY = get_configurable_value(
        "OpenAI API Key",
        [args.openai_api_key],
        "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",
    )

    client = OpenAI(api_key=OPENAI_API_KEY)

    TARGET_URL = os.getenv("TARGET_URL")
    X_API_KEY = os.getenv("X_API_KEY")

    if not os.path.exists(args.output_dir):
        os.makedirs(args.output_dir)

    test_cases = []
    for filename in sorted(os.listdir(f"{args.test_suit_dir}")):
        if filename == ".DS_Store":
            continue
        with open(f"{args.test_suit_dir}/{filename}", "r") as file:
            test_cases.append(yaml.safe_load(file))
    assistant_name = get_configurable_value(
        "Assistant ID",
        [args.assistant_name, os.getenv("ASSISTANT_ID")],
        test_cases[0]["assistant_name"],
    )
    model_name = make_request()(url=f"chatbot/assistants/{quote(assistant_name)}", method="GET").json()['platforms'][0]['model']
    with concurrent.futures.ThreadPoolExecutor() as executor:
        tasks = {
            executor.submit(process_test, test_case, attempt, assistant_name): (
                test_case["conversation_name"],
                attempt,
            )
            for test_case in test_cases
            for attempt in range(args.runs_per_case)
        }

        results = {}
        for future in concurrent.futures.as_completed(tasks):
            future_args = tasks[future]

            if future_args[0] not in results:
                results[future_args[0]] = []

            try:
                result = future.result()
                results[future_args[0]].append(result)
            except Exception as e:
                results[future_args[0]].append({"error": str(e)})
                print(f"An error occurred: {e}")
            save_results(results)

    connection_issue = 0
    total = 0
    failed = 0
    failed_runs = []
    total_elapsed_times = []
    total_input_tokens = []
    total_output_tokens = []
    code_interpreter_total_price = 0
    code_interpreter_usage_count = 0
    for testcase, runs in results.items():
        elapsed_times = []
        input_tokens = []
        output_tokens = []
        for i, r in enumerate(runs):
            total += 1

            if isinstance(r, dict) and 'elapsed_time' in r:
                elapsed_times.append(r['elapsed_time'])
                total_elapsed_times.append(r['elapsed_time'])
            if isinstance(r, dict) and 'tokens_usage' in r:
                input_tokens.append(r['tokens_usage']['input_tokens'])
                output_tokens.append(r['tokens_usage']['output_tokens'])
                total_input_tokens.append(r['tokens_usage']['input_tokens'])
                total_output_tokens.append(r['tokens_usage']['output_tokens'])
                if isinstance(r, dict) and 'is_code_interpreter_used' in r:
                    code_interpreter_total_price += 0.03
                    code_interpreter_usage_count += 1
            if r.get("error") == "No chat threads found.":
                connection_issue += 1
            elif r.get("diff_result"):
                failed += 1
                failed_runs.append(f"{testcase}. Run {i + 1}")
        if elapsed_times:
            print(f"Average Elapsed Time for '{testcase}' Test Case Runs:", sum(elapsed_times)/len(elapsed_times))
        else:
            print(f"No elapsed_time found for '{testcase}' Test Case Runs. Possible reason - incorrect test case type.")
        if input_tokens:
            print(f"Average Input Tokens for '{testcase}' Test Case Runs:", sum(input_tokens)/len(input_tokens))
        if output_tokens:
            print(f"Average Output Tokens for '{testcase}' Test Case Runs:", sum(output_tokens)/len(output_tokens))
    success = total - connection_issue - failed
    print(f"Success rate: {success / total * 100:.2f} %")
    print(f"Connection failure rate: {connection_issue / total * 100:.2f} %")
    print(f"Other failure rate: {failed / total * 100:.2f} %")
    print("Average Elapsed Time for all Test Case Runs:", sum(total_elapsed_times) / len(total_elapsed_times))
    average_input_tokens = sum(total_input_tokens) / len(total_input_tokens)
    print("Average Input Tokens for all Test Case Runs:", average_input_tokens)
    average_output_tokens = sum(total_output_tokens) / len(total_output_tokens)
    print("Average Output Tokens for all Test Case Runs:", average_output_tokens)
    average_input_price = average_input_tokens * MODEL_PRICING[model_name]['input_tokens'] / 1000
    average_output_price = average_output_tokens * MODEL_PRICING[model_name]['output_tokens'] / 1000
    print("Total costs for code interpreter:", code_interpreter_total_price, "It was used", code_interpreter_usage_count, "times out of ", len(total_output_tokens), "runs")
    average_total_cost = average_input_price + average_output_price + (code_interpreter_total_price / len(total_output_tokens))
    print(f"Average costs for {model_name}: ", average_total_cost)
    from pprint import pp

    print("Failed runs")
    pp(failed_runs)
