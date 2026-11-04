from drf_spectacular.extensions import OpenApiAuthenticationExtension

class PortalSessionScheme(OpenApiAuthenticationExtension):
    target_class = 'portal.permissions.PortalSessionAuthentication'
    name = 'portalSession'
    def get_security_definition(self, auto_schema):
        return {'type': 'apiKey', 'in': 'cookie', 'name': 'ti_session', 'description': 'Session after password change and MFA; unsafe requests also require X-CSRFToken.'}
