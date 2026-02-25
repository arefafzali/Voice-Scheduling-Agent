from __future__ import annotations

from unittest.mock import patch

from app.integrations.google_calendar_integration import GoogleCalendarIntegration


@patch("app.integrations.google_calendar_integration.build")
@patch("app.integrations.google_calendar_integration.Credentials")
def test_calendar_client_uses_refresh_token(mock_credentials, mock_build) -> None:
    credentials_instance = mock_credentials.return_value
    integration = GoogleCalendarIntegration(refresh_token="refresh-token-123", calendar_id="primary")

    credentials_instance.refresh.assert_called_once()
    mock_build.assert_called_once()
    assert integration is not None
