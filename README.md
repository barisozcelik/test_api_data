# Configure Open AI API Key in Account Manager
During the deployment process, the configuration bundle retrieves the OpenAI API Key from the Account Manager and utilizes it.

## How to set Open AI Key in Account Manager

**Sample Curl Command:**
```bash
curl --location 'https://[SUBDOMAIN].staircaseapi.com/account/component/credentials' \
--header 'x-api-key: [API_KEY]' \
--header 'Content-Type: application/json' \
--data '{
    "partner": "OpenAI",
    "product": "GPT4",
    "type": "production",
    "credentials": {
        "api_key": "test"
    }
}'
```
Ensure to replace [SUBDOMAIN] with your specific endpoint and [API_KEY] with your actual API key. This configuration is essential for seamless integration and operation of OpenAI's GPT4 within your application.


# How to Create an Assistant

- Create a folder under `assistants/data` with the assistant's name.
- In this folder, create an assistant definition file named `assistant.json`.
- If you wish to add static files to the assistant, create a folder named `files`.
- Place any static files you wish to include within the `files` folder.

## Assistant Definition

The `assistant.json` file should contain the following required properties:

- `name` (String): The name of the assistant.
- `description` (String): A description of the assistant.
- `instructions` (String): Instructions for GPT.
- `tools`: An array of defined tools for the assistant.

### Tool Definition

Each tool element within the `tools` array should have the following required properties:

- `type` (String): The type of the tool, which can be either `retrieval`, `function`, or `code_interpreter`.
- If the `type` is `function`, it should contain:
    - `function` (Object): The definition of the function.

#### Function Definition

The `function` object should have the following required properties:

- `name` (String): The name of the function.
- `description` (String): A description of the function.
- `parameters` (Object): Parameters for the function. This should be a valid JSON schema.


### Offical Links for OpenAI API:
 - https://platform.openai.com/docs/api-reference/introduction
