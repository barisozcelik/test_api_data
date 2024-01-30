from unittest.mock import patch, MagicMock

from assistants.handler import retrieve_gpt_api_key, verify_assistant_data


def test_retrieve_gpt_api_key_success():
    # Mocking requests and boto3 Session
    with patch('assistants.handler.make_request') as mock_make_request, \
            patch('assistants.handler.boto3.Session') as mock_session:
        mock_make_request.return_value.json.return_value = [{"api_key": "test_api_key"}]

        # Mock credentials
        mock_session.return_value.get_credentials.return_value = MagicMock(
            access_key='test_access_key',
            secret_key='test_secret_key',
            token='test_token'
        )

        # Call the function
        result = retrieve_gpt_api_key("test_domain", "test_api_key")

        # Assertions
        assert result == "test_api_key"
        mock_make_request.assert_called_once()


def test_retrieve_gpt_api_key_failure():
    with patch('assistants.handler.make_request') as mock_make_request, \
            patch('assistants.handler.boto3.Session') as mock_session:
        mock_make_request.return_value.json.return_value = [{}]

        mock_session.return_value.get_credentials.return_value = MagicMock(
            access_key='test_access_key',
            secret_key='test_secret_key',
            token='test_token'
        )

        result = retrieve_gpt_api_key("test_domain", "test_api_key")
        assert result is None
        mock_make_request.assert_called_once()


def test_verify_assistant_data_valid():
    data = {
        "name": "Test Assistant",
        "description": "Test Description",
        "instructions": "Test Instructions",
        "tools": [{"type": "function", "function": {
            "description": "Test Function",
            "name": "TestName",
            "parameters": {"type": "object", "properties": {}}
        }}]
    }
    is_valid, message = verify_assistant_data(data)
    assert is_valid
    assert message == "Object is valid."


def test_verify_assistant_data_invalid():
    data = {
        "name": "",
        "description": "Test Description",
        "instructions": "Test Instructions",
        "tools": [{"type": "unknown_type"}]
    }
    is_valid, message = verify_assistant_data(data)
    assert not is_valid
