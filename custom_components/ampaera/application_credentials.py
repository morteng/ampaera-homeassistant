"""Application credentials platform for Ampæra Energy OAuth2.

This enables OAuth2 authentication flow with the Ampæra cloud service.
Users can authenticate by clicking "Connect" in HA, logging into Ampæra,
and being redirected back with an access token.

References:
- https://developers.home-assistant.io/docs/config_entries_config_flow_handler/#oauth2
- https://developers.home-assistant.io/docs/integration_setup_info#application-credentials
"""

from __future__ import annotations

from homeassistant.components.application_credentials import AuthorizationServer
from homeassistant.core import HomeAssistant

from .const import (
    OAUTH_AUTHORIZE_URL,
    OAUTH_TOKEN_URL,
)


async def async_get_auth_implementation(
    hass: HomeAssistant,  # noqa: ARG001
    auth_domain: str,  # noqa: ARG001
    credential: dict,  # noqa: ARG001
) -> AuthorizationServer:
    """Return auth implementation for the OAuth2 flow.

    This is called by Home Assistant when setting up OAuth2 config flow.
    We return the Ampæra authorization server details.

    Args:
        hass: Home Assistant instance
        auth_domain: The integration domain (ampaera)
        credential: The application credential dict

    Returns:
        AuthorizationServer with Ampæra OAuth endpoints
    """
    return AuthorizationServer(
        authorize_url=OAUTH_AUTHORIZE_URL,
        token_url=OAUTH_TOKEN_URL,
    )


async def async_get_authorization_server(
    hass: HomeAssistant,  # noqa: ARG001
) -> AuthorizationServer:
    """Return the authorization server for Ampæra.

    This is the primary method Home Assistant calls to get OAuth server info.

    Args:
        hass: Home Assistant instance

    Returns:
        AuthorizationServer with Ampæra OAuth endpoints
    """
    return AuthorizationServer(
        authorize_url=OAUTH_AUTHORIZE_URL,
        token_url=OAUTH_TOKEN_URL,
    )


async def async_get_description_placeholders(
    hass: HomeAssistant,  # noqa: ARG001
) -> dict[str, str]:
    """Return description placeholders for the config flow.

    These are shown in the application credentials UI.
    """
    return {
        "more_info_url": "https://docs.ampaera.com/homeassistant/oauth",
        "create_creds_url": "https://xn--ampra-ura.no/settings/integrations",
    }
