import os
import time
from http import HTTPStatus
import json

import requests
import websocket
from threading import Thread
import pytest

# Global variables
ws_client = None
service_name = "mortgageAssistantApp-chat-ui"


# SET THE FILE THAT YOU WANT TO TEST
SELECTED_TEST_CASE = "test_conversation_2.json"

TEST_DATA_PATH = os.path.join(os.path.dirname(__file__), "test_conversations")
CONVERSATION_LOGS_PATH = os.path.join(os.path.dirname(__file__), "conversation_logs")
REQUIRED_CONTAINERS = [
    "addresses", "people", "communications", "employments", "incomes",
    "relationships", "residences", "assets", "liabilities", "ownerships",
    "leads", "declarations", "government_monitoring"
]

if not os.path.exists(CONVERSATION_LOGS_PATH):
    os.makedirs(CONVERSATION_LOGS_PATH)


# Function to send messages to the WebSocket hook
def send_message_to_hook(message, conversation_log):
    if "blob_id" in message:
        message = json.loads(message)
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

    global ws_client
    if ws_client:
        ws_client.send(message_to_send)
        conversation_log.append({"sender": "user", "message": message})
        print(f"\nUser Message:\n {message}")
    else:
        print("WebSocket client is not connected.")


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


# Function to run the WebSocket client
def run_websocket(ws_url, test_conversation, conversation_log):
    conversation_iter = iter(test_conversation)  # Create an iterator for the test conversation

    def on_open(ws):
        global ws_client
        ws_client = ws
        print("WebSocket connection opened.")
        try:
            first_message = next(conversation_iter)  # Get the first message from the test conversation
            send_message_to_hook(first_message, conversation_log)
        except StopIteration:
            print("Test conversation is empty.")
            ws.close()

    def on_message(ws, message):
        text_message = extract_question_from_message(message, conversation_log)
        print("\nReceived Message:\n", text_message)
        try:
            next_message = next(conversation_iter)  # Get the next message from the test conversation
            send_message_to_hook(next_message, conversation_log)
        except StopIteration:
            print("End of test conversation reached.")
            ws.close()

    ws = websocket.WebSocketApp(ws_url, on_open=on_open, on_message=on_message)
    ws.run_forever()


# Function to start the WebSocket application with a given conversation
def start_application(ws_url, prompts, conversation_name, transaction_id, make_request):
    conversation_log = []
    print(f"\nTest is starting for conversation: {conversation_name} transaction_id: {transaction_id}\n")
    ws_thread = Thread(target=run_websocket, args=(ws_url, prompts, conversation_log))
    ws_thread.start()
    ws_thread.join()  # Wait for the thread to finish
    save_conversation_log(conversation_log, f"{conversation_name}-{transaction_id}")
    # waiting for Persistence Bot
    time.sleep(120)
    check_success_condition(make_request, transaction_id, conversation_name)


def fetch_thread_id(make_request, transaction_id):
    response = make_request(f"chatbot/threads?transaction_id={transaction_id}", method="GET")
    if response.status_code == HTTPStatus.OK:
        chat_threads = response.json().get("chat_threads", [])
        if chat_threads:
            return chat_threads[0].get("open_ai_thread_id", "")
    return None


def send_missing_containers_to_slack(thread_id, transaction_id, missing_containers, conversation_name):
    formatted_missing = "\n".join([f"- {item}" for item in missing_containers]) if missing_containers else "None"
    playground_link = f"https://platform.openai.com/playground?thread={thread_id}"
    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "*ChatMTG Failed Test Result*\n"
                    f"• *Test Case Name:* {conversation_name}\n"
                    f"• *Thread ID:* {thread_id}\n"
                    f"• *Playground Link:* {playground_link}\n"
                    f"• *Transaction ID:* {transaction_id}\n"
                    f"• *Missing containers in recorded data:*\n{formatted_missing}"
                ),
            },
        }
    ]
    url = "https://hooks.slack.com/services/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"
    data = {"blocks": blocks}
    headers = {"Content-type": "application/json"}
    response = requests.post(url, json=data, headers=headers)
    response.raise_for_status()


def send_success_message_to_slack(thread_id, transaction_id, conversation_name):
    playground_link = f"https://platform.openai.com/playground?thread={thread_id}"
    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "*ChatMTG Success Test Result*\n"
                    f"• *Test Case Name:* {conversation_name}\n"
                    f"• *Thread ID:* {thread_id}\n"
                    f"• *Playground Link:* {playground_link}\n"
                    f"• *Transaction ID:* {transaction_id}"
                ),
            },
        }
    ]
    url = "https://hooks.slack.com/services/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"
    data = {"blocks": blocks}
    headers = {"Content-type": "application/json"}
    response = requests.post(url, json=data, headers=headers)
    response.raise_for_status()


def check_success_condition(make_request, transaction_id, conversation_name):
    recorded_data = retrieve_stored_data(make_request, transaction_id)
    not_found_containers = [container for container in REQUIRED_CONTAINERS if container not in recorded_data]

    thread_id = fetch_thread_id(make_request, transaction_id)
    if thread_id:
        if not_found_containers:
            send_missing_containers_to_slack(thread_id, transaction_id, not_found_containers, conversation_name)
        else:
            send_success_message_to_slack(thread_id, transaction_id, conversation_name)


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


def convert_query_results_to_collection_structure(frame, all_recorded_data_so_far):
    res = all_recorded_data_so_far
    objects = {}
    collection = {}
    for triple in res:
        cur_id = triple["data"]["value"].split("/")[-1]
        if cur_id not in objects:
            objects[cur_id] = {}
        predicate = triple["p"]["value"].split("/")[-1].split("#")[-1]
        if predicate in objects[cur_id]:
            if isinstance(objects[cur_id][predicate], list):
                objects[cur_id][predicate].append(triple["o"]["value"].split("/")[-1])
            else:
                objects[cur_id][predicate] = [
                    objects[cur_id][predicate],
                    triple["o"]["value"].split("/")[-1],
                ]
        else:
            objects[cur_id][predicate] = triple["o"]["value"].split("/")[-1]

    for obj_id in objects:
        obj_type = objects[obj_id]["type"]
        container = find_container(obj_type, frame)
        if not container:
            container = 'relationships'

        if container not in collection:
            collection[container] = []
        objects[obj_id]["@id"] = obj_id
        objects[obj_id]["@type"] = objects[obj_id].pop("type")
        collection[container].append(objects[obj_id])

    return collection


def retrieve_stored_data(make_request, transaction_id):
    frame_response = make_request("persistence/v3/jsonld/frame", method="GET")
    assert frame_response.status_code == HTTPStatus.OK
    frame = frame_response.json()
    query = f"""
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX sc: <https://www.staircase.co/ontology/>
        PREFIX sci: <https://www.staircase.co/>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>

        SELECT DISTINCT ?data ?p ?o
        WHERE {{
            ?collection sc:has_transaction/sc:transaction_identifier "{transaction_id}";
                sc:has_data ?data .
            ?data ?p ?o .
            }}
    """
    payload = f"query={query}"
    query_response = make_request("persistence/graph/sparql", method="POST", data=payload, headers={
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    })
    assert query_response.status_code == HTTPStatus.OK
    query_result = query_response.json()["results"]["bindings"]
    recorded_data_so_far = convert_query_results_to_collection_structure(frame=frame,
                                                                         all_recorded_data_so_far=query_result)
    return recorded_data_so_far


# Function to save conversation log to a JSON file
def save_conversation_log(conversation_log, conversation_name):
    file_path = os.path.join(CONVERSATION_LOGS_PATH, f"{conversation_name}_log.json")
    with open(file_path, 'w') as file:
        json.dump(conversation_log, file, indent=4)
    print(f"Conversation log saved to {file_path}")


def extract_specific_case():
    test_files = [f for f in os.listdir(TEST_DATA_PATH) if f.endswith('.json')]
    for file_name in test_files:
        if file_name == SELECTED_TEST_CASE:
            file_path = os.path.join(TEST_DATA_PATH, file_name)
            with open(file_path, 'r') as f:
                conversation = json.load(f)
                yield conversation


def create_transaction(make_request):
    response = make_request("persistence/transactions", method="POST")
    assert response.status_code == HTTPStatus.CREATED
    transaction_id = response.json()["transaction_id"]
    return transaction_id


# PyTest to run scenarios
@pytest.mark.parametrize("test_case", extract_specific_case())
def test_single_scenario(make_request, test_case):
    transaction_id = create_transaction(make_request)
    conversation_name = test_case.get("conversation_name")
    ws_url = f'wss://console-ws.exchange-prod.staircaseapi.com/ws/?payload={transaction_id}_{service_name}'
    prompts = test_case.get("prompts")
    start_application(ws_url, prompts, conversation_name, transaction_id, make_request)
