import os
from json import load, dumps, JSONDecodeError
import yaml, json

import openai
import boto3
from aws_requests_auth import aws_auth
import requests

assistant_data_folder = os.path.join(os.path.dirname(__file__), "data")
ASSISTANT_FOLDER_NAME = ""


def make_request(url, method, headers, **options):
    resp = requests.request(
        url=url,
        method=method,
        headers=headers,
        **options,
    )
    resp.raise_for_status()
    return resp


def retrieve_gpt_api_key(domain, api_key):
    result = None

    credentials = boto3.Session().get_credentials()
    resp = make_request(
        domain=domain,
        api_key=api_key,
        params={"partner": "OpenAI", "product": "loan_officer_gpt"},
        auth=aws_auth.AWSRequestsAuth(
            aws_access_key=credentials.access_key,
            aws_secret_access_key=credentials.secret_key,
            aws_token=credentials.token,
            aws_host=domain,
            aws_region="us-east-1",
            aws_service="execute-api",
        ),
    ).json()[0]
    if "api_key" in resp:
        result = resp["api_key"]
    return result


def create_files(domain, api_key, assistant_path, openai_assistant_id):
    openai.api_key = retrieve_gpt_api_key(domain, api_key)
    files_folder = os.path.join(assistant_path, "files")
    if not os.path.exists(files_folder):
        print(f"No files found in {files_folder}")
        return

    gpt_files = os.listdir(files_folder)
    if not gpt_files:
        print("No files to add.")
        return

    print(f"Files to Add - {gpt_files}")

    try:
        current_list = openai.beta.assistants.files.list(assistant_id=openai_assistant_id).data
        for current_file in current_list:
            openai.beta.assistants.files.delete(
                assistant_id=openai_assistant_id, file_id=current_file.id
            )
            openai.files.delete(current_file.id)
    except Exception as e:
        print(f"Error during file deletion: {e}")
        return
    for gpt_file in gpt_files:
        gpt_file_data_path = os.path.join(files_folder, gpt_file)
        try:
            with open(gpt_file_data_path, "rb") as file_data:
                file_response = openai.files.create(
                    file=file_data, purpose="assistants"
                )
                openai.beta.assistants.files.create(
                    assistant_id=openai_assistant_id, file_id=file_response.id
                )
        except Exception as e:
            print(f"Error during file upload for {gpt_file}: {e}")


def verify_assistant_data(data):
    # Validate string fields
    string_fields_to_validate = ["assistant_name", "description", "instructions"]
    for field in string_fields_to_validate:
        if field not in data:
            return False, f"Field '{field}' is missing."
        if data[field] is None or not data[field] or len(data[field]) == 0:
            return False, f"Field '{field}' is null, empty, or zero length."

    # Validate 'tools' field
    if (
            "tools" not in data
            or not isinstance(data["tools"], list)
            or len(data["tools"]) == 0
    ):
        return False, "Field 'tools' is invalid."

    valid_tool_types = ["code_interpreter", "retrieval", "function"]
    for tool in data["tools"]:
        if "tool_type" not in tool or tool["tool_type"] not in valid_tool_types:
            return False, "Invalid tool type."

        if tool["tool_type"] == "function":
            if "function" not in tool:
                return False, "Function object is missing."

            for f_field in ["name", "description", "parameters"]:
                if f_field not in tool["function"] or not tool["function"][f_field]:
                    return False, f"Field '{f_field}' in function is invalid."

            try:
                dumps(
                    tool["function"]["parameters"]
                )  # Test if parameters is a valid JSON
            except ValueError:
                return False, "Parameters is not a valid JSON schema."

    # Validate 'platforms' field
    if (
            "platforms" not in data
            or not isinstance(data["platforms"], list)
            or len(data["platforms"]) == 0
    ):
        return False, "Field 'platforms' is missing or invalid."

    valid_platforms = ["OpenAI", "Google"]  # Add more as applicable
    for platform in data["platforms"]:
        if (
                "platform_name" not in platform
                or platform["platform_name"] not in valid_platforms
        ):
            return False, "Invalid platform name."
        if "model" not in platform:
            return False, "Model field is missing in platform."

    # Adding additional check for assistant_name - assistant_name_to_exclude relationship
    for tool in data.get("tools", []):
        if tool.get("http_method") == "POST" and tool.get("path") == "chatbot/orchestrator":
            function = tool.get("function")
            if function and function.get("name") == "switchToNextAssistant":
                # Validate assistant_name_to_exclude parameter
                parameters = function.get("parameters")
                if "required" not in parameters or "assistant_name_to_exclude" not in parameters.get("required"):
                    return False, "assistant_name_to_exclude parameter should be required."
                if not parameters or not parameters.get(
                        "properties") or "assistant_name_to_exclude" not in parameters.get("properties"):
                    return False, "assistant_name_to_exclude parameter is missing."

                try:
                    param_data = dumps(parameters)
                    param_json = json.loads(param_data).get("properties")
                    if "const" not in param_json["assistant_name_to_exclude"]:
                        return False, "const field is missing in assistant_name_to_exclude."
                    if param_json["assistant_name_to_exclude"]["const"] != data["assistant_name"]:
                        return False, "const value in assistant_name_to_exclude does not match assistant_name."
                except JSONDecodeError:
                    return False, "Parameters is not a valid JSON schema."

    return True, "Object is valid."


def create_or_modify_assistant(chatbot_domain, api_key):
    # URL for listing assistants
    list_assistants_url = f"https://{chatbot_domain}/chatbot/assistants"
    headers = {"x-api-key": api_key}

    assistants = os.listdir(assistant_data_folder)
    assistants = [ASSISTANT_FOLDER_NAME]

    for assistant in assistants:
        if assistant == ".DS_Store":
            continue
        assistant_path = os.path.join(
            assistant_data_folder, assistant, "assistant.yaml"
        )
        if not os.path.exists(assistant_path):
            print(f"Assistant definition is missing for {assistant}")
            continue

        with open(assistant_path, "r") as file:
            assistant_data = yaml.safe_load(file)

        verify_result, message = verify_assistant_data(assistant_data)
        if not verify_result:
            print(f"Verification failed for {assistant}: {message}")
            continue

        # create_files(chatbot_domain, api_key, os.path.join(assistant_data_folder, assistant), assistant_id)
        response = make_request(
            list_assistants_url, "POST", headers, json=assistant_data
        )
        print(
            f"Assistant {response.json()['assistant_name']} registered. Name - {assistant_data['assistant_name']}"
        )


def handler(event, context):
    create_or_modify_assistant(event["SERVICE_DOMAIN_NAME"], event["SERVICE_API_KEY"])


if __name__ == "__main__":
    ASSISTANT_FOLDER_NAME = ""  # Sample: residency_collector,
    create_or_modify_assistant("", "")
