import argparse
import concurrent.futures
import json
import os
import time
from http import HTTPStatus
from threading import Thread, Timer
from urllib.parse import urlsplit

import requests
import websocket
from dotenv import load_dotenv
from deepdiff import DeepDiff
from openai import OpenAI


WEBSOCKET_TTL = 120
NUMBER_OF_RUNS_PER_TEST_CASE = 10


def start_application(ws_url, prompts, conversation_name, transaction_id, websocket_ttl):
    conversation_log = []
    print(f"\nTest is starting for conversation: {conversation_name} transaction_id: {transaction_id}\n")
    ws_thread = Thread(target=run_websocket, args=(ws_url, prompts, conversation_log, websocket_ttl))
    ws_thread.start()
    ws_thread.join()  # Wait for the thread to finish
    return conversation_log


def run_websocket(ws_url, test_conversation, conversation_log, websocket_ttl):
    ws_client = None
    timer = None

    conversation_iter = iter(test_conversation)  # Create an iterator for the test conversation

    def on_open(ws):

        def close_ws():
            print('Timeout reaches. Closing WebSocket.')
            ws.close()

        nonlocal ws_client
        nonlocal timer 
        timer = Timer(websocket_ttl, close_ws)
        timer.start()

        ws_client = ws
        print("WebSocket connection opened.")
        try:
            first_message = next(conversation_iter)  # Get the first message from the test conversation
            send_message_to_hook(first_message, conversation_log, ws_client)
        except StopIteration:
            print("Test conversation is empty.")
            timer.cancel()
            ws.close()

    def on_message(ws, message):
        text_message = extract_question_from_message(message, conversation_log)
        print("\nReceived Message:\n", text_message)
        try:
            next_message = next(conversation_iter)  # Get the next message from the test conversation
            send_message_to_hook(next_message, conversation_log, ws_client)
        except StopIteration:
            print("End of test conversation reached.")
            timer.cancel()
            ws.close()
            

    ws = websocket.WebSocketApp(ws_url, on_open=on_open, on_message=on_message)
    ws.run_forever()


# Function to send messages to the WebSocket hook
def send_message_to_hook(message, conversation_log, ws_client):
    if "blob_id" in message:
        blob_id = message["blob_id"]
        text_message = message["message"]
        message_to_send = json.dumps({
            "action": "user_message",
            "message": [
                {
                    "type": "text",
                    "text": {"value": text_message}
                }, {
                    "type": "file",
                    "file": {
                        "name": f"{blob_id}.pdf",
                        "mime_type": "application/pdf",
                        "blob_id": blob_id
                    }
                }
            ]
        })

    else:
        message_to_send = json.dumps({
            "action": "user_message",
            "message": [
                {
                    "type": "text",
                    "text": {"value": message}
                }
            ]
        })

    try:
        ws_client.send(message_to_send)
        conversation_log.append({"sender": "user", "message": message})
        print(f"\nUser Message:\n {message}")
    except Exception as e:
        print(f'Error while sending message to the websocket: {e}')


# Function to extract question from the message
def extract_question_from_message(message, conversation_log):
    try:
        message_data = json.loads(message)
        if message_data.get("action") == "service_message":
            messages = message_data.get("message", [])
            responses = []
            for message in messages:
                text_content = message.get("text", {})
                conversation_log.append({"sender": "assistant", "message": text_content.get("value", "")})
                responses.append(text_content.get("value"))
            return " ".join(responses)
    except json.JSONDecodeError:
        print("Error decoding JSON from the message")
    return ""


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
    recorded_data_so_far = response.json()['message']['all_recorded_data_so_far']
    return recorded_data_so_far


def create_transaction(make_request):
    response = make_request("persistence/transactions", method="POST")
    assert response.status_code == HTTPStatus.CREATED
    transaction_id = response.json()["transaction_id"]
    return transaction_id


def retrieve_main_thread_id(make_request, transaction_id):
    response = make_request(f"chatbot/threads?transaction_id={transaction_id}", method='GET')
    chat_threads = response.json().get('chat_threads', [])
    if not chat_threads:
        raise Exception('No chat threads found.')
    chat_threads = sorted(chat_threads, key=lambda ct: ct['thread_created_at'])
    return chat_threads[0]['open_ai_thread_id']


def make_request():
    def f(url, **options) -> requests.Response:
        target = urlsplit(TARGET_URL)
        url = f"{target.scheme}://{target.hostname}/{url}"
        headers = options.pop("headers", {})
        headers["x-api-key"] = X_API_KEY
        return requests.request(url=url, headers=headers, **options)

    return f


def process_test(test_case, attempt, websocket_ttl, wait_for_graph_bot):
    transaction_id = create_transaction(make_request())

    if test_case.get('init_collection'):
        make_request()(
            url=f'persistence/transactions/{transaction_id}/collections',
            method='POST',
            json={
                'metadata': {
                    'version': 3,
                    'validation': False
                },
                'data': test_case.get('init_collection')
            }
        )

    conversation_name = test_case.get("conversation_name")
    assistant_id = test_case.get('assistant_id')

    service_name = test_case['conversation_name'].replace('_', '-')

    make_request()(
        'console-service-api/webhooks',
        method='POST',
        json={
            'webhook_url': f"https://exchange-prod.staircaseapi.com/chatbot/assistants/{assistant_id}/messaging",
            'service_name': service_name
        }
    )
    time.sleep(3)

    ws_url = f'wss://console-ws.exchange-prod.staircaseapi.com/ws/?payload={transaction_id}_{service_name}'
    prompts = test_case.get("prompts")

    conversation_log = start_application(ws_url, prompts, conversation_name, transaction_id, websocket_ttl)
    time.sleep(wait_for_graph_bot)

    if 'expected_v3' in test_case:
        print('Warning: Persistence tests are deprecated, make sure to use Function Call tests')
        recorded_data = retrieve_stored_data(make_request(), transaction_id)

        exclude_regex_paths = [
            f"\\['{item}'\\]"
            for item in test_case['exclude_regex_paths']
        ]

        diff_result = DeepDiff(
            test_case['expected_v3'],
            recorded_data,
            ignore_order=True, 
            exclude_paths=["root['chat_threads']"],
            exclude_regex_paths=exclude_regex_paths
        )
        return {
            'conversation_name': test_case['conversation_name'],
            'assistant_id': test_case['assistant_id'],
            'transaction_id': transaction_id,
            'prompts': test_case['prompts'],
            'expected': test_case['expected_v3'],
            'actual': recorded_data,
            'diff_result': json.loads(diff_result.to_json()),
            'conversation_log': conversation_log,
            'test_type': 'Persistence'
        }
    elif 'expected_function_calls' in test_case:
        thread_id = retrieve_main_thread_id(make_request(), transaction_id)

        runs = client.beta.threads.runs.list(
            thread_id=thread_id,
            order='desc'
        )
        
        if not runs.data:
            raise Exception(f'No runs found for {thread_id} thread')
        
        latest_run = runs.data[0]

        run_steps = client.beta.threads.runs.steps.list(
            thread_id=thread_id,
            run_id=latest_run.id,
            limit=100
        )

        tools_called = []
        for run_step in run_steps.data:
            if run_step.step_details.type != 'tool_calls':
                continue
            for tool_call in run_step.step_details.tool_calls:
                if tool_call.type != 'function':
                    continue
                tools_called.append({
                    'name': tool_call.function.name,
                    'arguments': json.loads(tool_call.function.arguments)
                })
        
        exclude_regex_paths = [
            f"\\['{item}'\\]"
            for item in test_case['exclude_regex_paths']
        ]

        diff_result = DeepDiff(
            test_case['expected_function_calls'],
            tools_called,
            ignore_order=True, 
            exclude_paths=["root['chat_threads']"],
            exclude_regex_paths=exclude_regex_paths
        )

        return {
            'conversation_name': test_case['conversation_name'],
            'assistant_id': test_case['assistant_id'],
            'transaction_id': transaction_id,
            'prompts': test_case['prompts'],
            'expected': test_case['expected_function_calls'],
            'actual': tools_called,
            'diff_result': json.loads(diff_result.to_json()),
            'conversation_log': conversation_log,
            'test_type': 'Function Call'
        }
    else:
        print('Unsupported test type. Make sure to use \'Function Call\' test type')
        return None
    

def save_results(results):
    for filename, result in results.items():
        with open(f'{args.output_dir}/{filename}.json', 'w') as file:
            json.dump(result, file, indent=4)


if __name__ == '__main__':
    client = OpenAI(api_key='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')

    parser = argparse.ArgumentParser()

    parser.add_argument('test_suit_dir', type=str, help='Path to the dir with test suit')
    parser.add_argument('output_dir', type=str, help='Path to the dir with test report')
    parser.add_argument('--websocket_ttl', type=int, default=WEBSOCKET_TTL, help='Weboscket TTL')
    parser.add_argument('--runs_per_case', type=int, default=NUMBER_OF_RUNS_PER_TEST_CASE, help='Number of Runs per Test Case')
    parser.add_argument('--wait_for_graph_bot', type=int, default=180)

    args = parser.parse_args()

    load_dotenv()

    TARGET_URL = os.getenv("TARGET_URL")
    X_API_KEY = os.getenv("X_API_KEY")

    if not os.path.exists(args.output_dir):
        os.makedirs(args.output_dir)


    test_cases = []
    for filename in sorted(os.listdir(f'{args.test_suit_dir}')):
        with open(f'{args.test_suit_dir}/{filename}', 'r') as file:
            test_cases.append(json.load(file))

    with concurrent.futures.ThreadPoolExecutor() as executor:
        tasks = {
            executor.submit(process_test, test_case, attempt, args.websocket_ttl, args.wait_for_graph_bot): (test_case['conversation_name'], attempt)
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
                results[future_args[0]].append({
                    'error': str(e)
                })
                print(f"An error occurred: {e}")
            save_results(results)
