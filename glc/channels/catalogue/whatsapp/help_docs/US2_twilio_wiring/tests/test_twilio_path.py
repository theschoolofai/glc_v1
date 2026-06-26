from unittest.mock import MagicMock, patch
from glc.channels.catalogue.whatsapp.help_docs.US2_twilio_wiring.scripts.twilio_sandbox import send_sandbox_message

@patch("glc.channels.catalogue.whatsapp.help_docs.US2_twilio_wiring.scripts.twilio_sandbox.Client")
@patch("os.getenv")
def test_twilio_sandbox_sends_message(mock_getenv, mock_client):
    def getenv_side_effect(key, default=None):
        mapping = {
            "TWILIO_ACCOUNT_SID": "sid",
            "TWILIO_AUTH_TOKEN": "token",
            "TWILIO_SANDBOX_NUMBER": "from",
            "TWILIO_TEST_TO": "to",
        }
        return mapping.get(key)

    mock_getenv.side_effect = getenv_side_effect

    # Mock message and client
    mock_message = MagicMock()
    mock_message.sid = "msg_sid"
    mock_message.status = "sent"
    mock_message.to = "to"
    mock_message.from_ = "from"
    mock_message.error_code = None
    mock_message.error_message = None

    # Configure client.messages.create and messages(sid).fetch
    instance = mock_client.return_value
    instance.messages.create.return_value = mock_message
    instance.messages.return_value.fetch.return_value = mock_message

    send_sandbox_message()

    # Assertions
    instance.messages.create.assert_called_once()
