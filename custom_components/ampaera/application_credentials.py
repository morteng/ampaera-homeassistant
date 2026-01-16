"""Application credentials platform for Ampæra Energy OAuth2.

This enables OAuth2 authentication flow with the Ampæra cloud service.
Uses a pre-registered public OAuth client (client_id: home-assistant)
so users don't need to create their own OAuth app.

References:
- https://developers.home-assistant.io/docs/config_entries_config_flow_handler/#oauth2
- https://developers.home-assistant.io/docs/integration_setup_info#application-credentials
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from typing import Any

from homeassistant.components.application_credentials import (
    AuthImplementation,
    AuthorizationServer,
    ClientCredential,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.config_entry_oauth2_flow import _encode_jwt
from yarl import URL

from .const import (
    DOMAIN,
    OAUTH_AUTHORIZE_URL,
    OAUTH_CLIENT_ID,
    OAUTH_TOKEN_URL,
)

# Storage for PKCE code verifiers (flow_id -> code_verifier)
_PKCE_VERIFIERS: dict[str, str] = {}


def _generate_code_verifier() -> str:
    """Generate a PKCE code verifier."""
    return secrets.token_urlsafe(32)


def _generate_code_challenge(verifier: str) -> str:
    """Generate a PKCE code challenge from the verifier."""
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


class AmperaOAuth2Implementation(AuthImplementation):
    """Ampæra OAuth2 implementation using pre-registered public client.

    This allows users to authenticate without creating their own OAuth app.
    The client_id 'home-assistant' is pre-registered on the Ampæra server.
    Includes PKCE support for enhanced security.

    Uses direct OAuth callbacks to the HA instance (via external_url) instead
    of routing through my.home-assistant.io. This enables multi-instance setups
    where each HA instance has its own external URL.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the Ampæra OAuth2 implementation."""
        super().__init__(
            hass=hass,
            auth_domain=DOMAIN,
            credential=ClientCredential(
                client_id=OAUTH_CLIENT_ID,
                client_secret="",  # Public client, no secret required
            ),
            authorization_server=AuthorizationServer(
                authorize_url=OAUTH_AUTHORIZE_URL,
                token_url=OAUTH_TOKEN_URL,
            ),
        )

    @property
    def redirect_uri(self) -> str:
        """Return the redirect URI using the HA instance's external URL.

        This bypasses my.home-assistant.io and uses direct OAuth callback,
        which works correctly for multi-instance setups where each HA
        instance has its own external URL.
        """
        # Get external URL from HA configuration (set in configuration.yaml)
        external_url = self.hass.config.external_url
        if external_url:
            return f"{external_url.rstrip('/')}/auth/external/callback"

        # Fallback to internal URL if no external URL configured
        internal_url = self.hass.config.internal_url
        if internal_url:
            return f"{internal_url.rstrip('/')}/auth/external/callback"

        # Last resort: use my.home-assistant.io (original HA behavior)
        return "https://my.home-assistant.io/redirect/oauth"

    @property
    def extra_authorize_data(self) -> dict:
        """Extra data to include in authorization request."""
        return {"scope": "ha:full"}

    async def async_generate_authorize_url(self, flow_id: str) -> str:
        """Generate the authorize URL with PKCE support."""
        # Generate PKCE code verifier and challenge
        code_verifier = _generate_code_verifier()
        code_challenge = _generate_code_challenge(code_verifier)

        # Store verifier for later token exchange
        _PKCE_VERIFIERS[flow_id] = code_verifier

        # Get the redirect URI from HA
        redirect_uri = self.redirect_uri

        # Build the authorize URL with PKCE
        url = URL(self.authorize_url).with_query({
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "state": _encode_jwt(self.hass, {"flow_id": flow_id, "redirect_uri": redirect_uri}),
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            **self.extra_authorize_data,
        })

        return str(url)

    async def async_resolve_external_data(self, external_data: Any) -> dict:
        """Resolve external data to tokens, including PKCE verifier."""
        # Get the code verifier for this flow
        flow_id = external_data.get("state", {}).get("flow_id", "")
        code_verifier = _PKCE_VERIFIERS.pop(flow_id, None)

        # Exchange the authorization code for tokens
        return await self._token_request({
            "grant_type": "authorization_code",
            "code": external_data["code"],
            "redirect_uri": external_data["state"]["redirect_uri"],
            "client_id": self.client_id,
            **({"code_verifier": code_verifier} if code_verifier else {}),
        })


async def async_get_auth_implementation(
    hass: HomeAssistant,
    auth_domain: str,  # noqa: ARG001
    credential: ClientCredential,  # noqa: ARG001
) -> AuthImplementation:
    """Return auth implementation for user-provided credentials.

    This is called when a user adds their own OAuth credentials.
    We still use our built-in implementation since the credentials
    are pre-registered.
    """
    return AmperaOAuth2Implementation(hass)


async def async_get_authorization_server(
    hass: HomeAssistant,  # noqa: ARG001
) -> AuthorizationServer:
    """Return the authorization server for Ampæra.

    This is called by Home Assistant to get OAuth server info.
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
        "more_info_url": "https://docs.ampaera.no/homeassistant/oauth",
        "create_creds_url": "https://xn--ampra-ura.no/settings/integrations",
    }
