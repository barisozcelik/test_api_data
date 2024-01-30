import json
import os
import time
from http import HTTPStatus
from threading import Thread, Timer
from urllib.parse import urlsplit

import pytest
import websocket
from dotenv import load_dotenv
from deepdiff import DeepDiff


TEST_DATA_PATH = os.path.join(os.path.dirname(__file__), "individual_test_conversations")
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
    recorded_data_so_far = convert_query_results_to_collection_structure(
        frame=frame,
        all_recorded_data_so_far=query_result
    )
    return recorded_data_so_far


def create_transaction(make_request):
    response = make_request("persistence/transactions", method="POST")
    assert response.status_code == HTTPStatus.CREATED
    transaction_id = response.json()["transaction_id"]
    return transaction_id


def extract_specific_case():
    test_dirs = [d for d in os.listdir(TEST_DATA_PATH)]
    for dir in test_dirs:
        test_files = [f for f in os.listdir(f'{TEST_DATA_PATH}/{dir}') if f.endswith('.json')]
        for file_name in test_files:
            file_path = os.path.join(TEST_DATA_PATH, dir, file_name)
            with open(file_path, 'r') as f:
                conversation = json.load(f)
                yield conversation


@pytest.mark.parametrize("test_case", extract_specific_case())
def test_individual_scenario(make_request, test_case):
    transaction_id = create_transaction(make_request)

    if test_case.get('init_collection'):
        make_request(
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

    make_request(
        'console-service-api/webhooks',
        method='POST',
        json={
            'webhook_url': f"https://exchange-prod.staircaseapi.com/chatbot/assistants/{assistant_id}/messaging",
            'service_name': 'test-assistant'
        }
    )
    time.sleep(3)

    ws_url = f'wss://console-ws.exchange-prod.staircaseapi.com/ws/?payload={transaction_id}_test-assistant'
    prompts = test_case.get("prompts")

    conversation_log = start_application(ws_url, prompts, conversation_name, transaction_id, WEBSOCKET_TTL)
    time.sleep(120)

    recorded_data = retrieve_stored_data(make_request(), transaction_id)

    exclude_regex_paths = [
        f"\\['{item}'\\]"
        for item in test_case['exclude_regex_paths']
    ]

    diff_result = DeepDiff(
        recorded_data, 
        test_case['expected_v3'], 
        ignore_order=True, 
        exclude_paths=["root['chat_threads']"],
        exclude_regex_paths=exclude_regex_paths
    )

    assert not diff_result
